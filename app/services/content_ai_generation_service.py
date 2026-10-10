"""Orchestrate async Content AI generation + SSE bridge (WAVE 2)."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Callable, Iterator

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.content_ai_async_rollout import async_enabled_for_user
from app.services.content_ai_generation_store import (
    TERMINAL_STATES,
    GenerationState,
    cancel_generation,
    create_generation,
    get_generation_for_user,
    ensure_schema,
)
from app.services.content_ai_generation_stream import (
    iter_events_until_terminal,
    read_events,
)
from app.services.tenant_org import resolve_organization_id

_LOG = logging.getLogger(__name__)


def build_idempotency_key(
    request: Request,
    user: User,
    payload: dict[str, Any],
) -> str:
    header = (
        (request.headers.get("Idempotency-Key") or "")
        or (request.headers.get("X-Request-Id") or "")
        or (request.headers.get("X-Request-ID") or "")
    ).strip()
    if header:
        return f"hdr:{header}"[:128]
    body_fp = hashlib.sha256(
        json.dumps(payload or {}, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:32]
    return f"fp:{int(user.id)}:{body_fp}"[:128]


def should_use_async_stream(user: User, request: Request) -> bool:
    return async_enabled_for_user(user, request=request)


def start_or_get_generation(
    db: Session,
    *,
    user: User,
    request: Request,
    payload: dict[str, Any],
    llm_gate: dict[str, Any],
    feature_key: str,
    organization_id: int | None = None,
) -> GenerationState:
    ensure_schema()
    org_id = resolve_organization_id(int(user.id), organization_id, db=db)
    idem = build_idempotency_key(request, user, payload)
    quote = llm_gate.get("quote") if isinstance(llm_gate.get("quote"), dict) else {}
    req_payload = dict(payload)
    req_payload.update(
        {
            "user_id": int(user.id),
            "organization_id": int(org_id),
            "feature_key": feature_key,
            "llm_gate": {
                "charge_credits": bool(llm_gate.get("charge_credits")),
                "unit_cost": int(llm_gate.get("unit_cost") or 0),
                "use_system_llm": bool(llm_gate.get("use_system_llm")),
                "prompt_word_count": llm_gate.get("prompt_word_count"),
                "quote": quote,
            },
        }
    )
    gen = create_generation(
        db,
        user_id=int(user.id),
        organization_id=int(org_id),
        idempotency_key=idem,
        request_payload=req_payload,
        credit_request_id=str(quote.get("request_id") or "")[:64] or None,
    )
    if gen.state in ("QUEUED",):
        from app.workers.content_ai_generation_tasks import enqueue_content_ai_generation

        enqueue_content_ai_generation(gen.generation_id)
    return gen


def generation_status_payload(gen: GenerationState) -> dict[str, Any]:
    out: dict[str, Any] = {
        "generation_id": gen.generation_id,
        "state": gen.state,
        "progress": gen.progress,
        "message": gen.message,
        "last_stream_seq": gen.last_stream_seq,
    }
    if gen.state == "COMPLETED" and isinstance(gen.result, dict):
        out["result"] = gen.result
        out["credits_charged"] = gen.credits_charged
    elif gen.state == "FAILED":
        out["error"] = gen.error or gen.message
    return out


def _event_to_sse(
    event: dict[str, Any],
    emit_delta: Callable[[str], str],
    emit_replace: Callable[[str], str],
    emit_wc: Callable[[dict[str, Any]], str],
    emit_ping: Callable[[], str],
    emit_error: Callable[..., str],
    emit_done: Callable[[], str],
) -> str | None:
    et = str(event.get("event") or "")
    data = event.get("data")
    if et == "ping":
        return emit_ping()
    if et == "delta":
        return emit_delta(str(data or ""))
    if et == "replace_html":
        return emit_replace(str(data or ""))
    if et == "word_count" and isinstance(data, dict):
        return emit_wc(data)
    if et == "error":
        if isinstance(data, dict):
            return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        return emit_error(internal=str(data or "error"))
    if et == "done":
        return emit_done()
    return None


def sse_bridge_generation(
    db: Session,
    *,
    generation_id: str,
    user: User,
    after_seq: int = 0,
    emit_delta: Callable[[str], str],
    emit_replace: Callable[[str], str],
    emit_wc: Callable[[dict[str, Any]], str],
    emit_ping: Callable[[], str],
    emit_error: Callable[..., str],
    emit_done: Callable[[], str],
) -> Iterator[str]:
    """Read Redis stream in order and emit legacy SSE events."""
    gen = get_generation_for_user(db, generation_id, user_id=int(user.id))
    if gen is None:
        yield emit_error(internal="generation_not_found")
        return

    seen_seq = int(after_seq)
    emitted_done = False

    def _terminal() -> bool:
        nonlocal emitted_done
        g2 = get_generation_for_user(db, generation_id, user_id=int(user.id))
        if g2 is None:
            return True
        if str(g2.state) in TERMINAL_STATES:
            return True
        return emitted_done

    # Replay buffered events first
    for ev in read_events(generation_id, after_seq=seen_seq):
        seq = int(ev.get("seq") or 0)
        if seq <= seen_seq:
            continue
        seen_seq = seq
        chunk = _event_to_sse(ev, emit_delta, emit_replace, emit_wc, emit_ping, emit_error, emit_done)
        if chunk:
            yield chunk
        if str(ev.get("event")) == "done":
            emitted_done = True
            return
        if str(ev.get("event")) == "error":
            return

    if _terminal() and not emitted_done:
        g2 = get_generation_for_user(db, generation_id, user_id=int(user.id))
        if g2 and g2.state == "COMPLETED" and isinstance(g2.result, dict):
            html = str(g2.result.get("html") or "")
            if html:
                yield emit_replace(html)
            wc = g2.result.get("word_count_meta")
            if isinstance(wc, dict) and wc:
                yield emit_wc(wc)
            yield emit_done()
            return
        if g2 and g2.state == "FAILED":
            yield emit_error(internal=str(g2.error or "failed"))
            return
        if g2 and g2.state == "CANCELLED":
            yield emit_error(internal="cancelled")
            return

    for ev in iter_events_until_terminal(generation_id, after_seq=seen_seq, is_terminal=_terminal):
        seq = int(ev.get("seq") or 0)
        if seq <= seen_seq:
            continue
        seen_seq = seq
        chunk = _event_to_sse(ev, emit_delta, emit_replace, emit_wc, emit_ping, emit_error, emit_done)
        if chunk:
            yield chunk
        if str(ev.get("event")) == "done":
            emitted_done = True
            return
        if str(ev.get("event")) == "error":
            return

    if not emitted_done:
        g2 = get_generation_for_user(db, generation_id, user_id=int(user.id))
        if g2 and g2.state == "COMPLETED":
            yield emit_done()
        elif g2 and g2.state == "FAILED":
            yield emit_error(internal=str(g2.error or "failed"))


def cancel_user_generation(db: Session, *, generation_id: str, user: User) -> dict[str, Any]:
    gen = cancel_generation(db, generation_id, user_id=int(user.id))
    if gen is None:
        raise HTTPException(status_code=404, detail="Generation not found")
    from app.services.content_ai_generation_stream import append_event

    append_event(generation_id, "error", {"ok": False, "message": "cancelled"})
    return generation_status_payload(gen)
