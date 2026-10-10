"""Execute Content AI generation in Celery worker (same LLM logic as sync stream)."""

from __future__ import annotations

import logging
from typing import Any

from app.db import SessionLocal
from app.models.user import User
from app.services.content_ai_generation_store import (
    complete_generation,
    fail_generation,
    is_cancelled,
    update_generation_progress,
)
from app.services.content_ai_generation_stream import append_event

_LOG = logging.getLogger(__name__)


def _check_cancelled(generation_id: str) -> bool:
    return is_cancelled(generation_id)


def run_content_ai_generation(generation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
  """
  Run LLM generation for one async job.
  Emits ordered Redis stream events; persists final result + billing in PG.
  """
  gid = str(generation_id)
  user_id = int(payload.get("user_id") or 0)
  if user_id <= 0:
    fail_generation(gid, error="missing_user_id")
    append_event(gid, "error", {"ok": False, "message": "missing_user_id"})
    return {"ok": False, "error": "missing_user_id"}

  db = SessionLocal()
  try:
    user = db.get(User, user_id)
    if user is None:
      fail_generation(gid, error="user_not_found")
      append_event(gid, "error", {"ok": False, "message": "user_not_found"})
      return {"ok": False, "error": "user_not_found"}

    llm_gate = payload.get("llm_gate") if isinstance(payload.get("llm_gate"), dict) else {}
    quote = llm_gate.get("quote") if isinstance(llm_gate.get("quote"), dict) else {}
    requested = str(payload.get("field") or "content").strip().lower()
    prompt_wc = llm_gate.get("prompt_word_count")
    feature_key = str(payload.get("feature_key") or "content_ai_article")

    from app.services.content_ai_credit_service import (
      charge_content_ai_write,
      reserve_content_ai_write,
      ContentAiCreditHold,
    )
    from app.services.content_ai_entitlement import record_content_ai_usage
    from app.services.cost_control.module_gates import content_ai_llm_gate
    from app.services.cost_control.context import get_active_cost_gate, set_active_cost_gate
    from app.services.user_api_access import load_llm_config_for_request

    hold: ContentAiCreditHold | None = None
    if llm_gate.get("charge_credits"):
      hold = reserve_content_ai_write(db, user, quote, field=requested)
      db.commit()

    append_event(gid, "ping", True)
    update_generation_progress(gid, progress=5, message="Starting LLM")

    if _check_cancelled(gid):
      if hold is not None:
        hold.release(reason="cancelled")
        db.commit()
      append_event(gid, "error", {"ok": False, "message": "cancelled"})
      return {"ok": False, "cancelled": True}

    llm_cfg = load_llm_config_for_request(db, user)
    if not llm_cfg:
      if hold is not None:
        hold.release(reason="llm_not_configured")
        db.commit()
      fail_generation(gid, error="llm_not_configured")
      append_event(gid, "error", {"ok": False, "message": "LLM not configured"})
      return {"ok": False, "error": "llm_not_configured"}

    gate_cm = content_ai_llm_gate(
      db,
      user,
      action="suggest_stream",
      field=requested,
      use_system_llm=bool(llm_gate.get("use_system_llm")),
      llm_cfg=llm_cfg,
      credit_cost=int(llm_gate.get("unit_cost") or 0),
      word_count=prompt_wc if requested == "content" else payload.get("target_word_count"),
    )
    gate_cm.__enter__()
    gate_snapshot = get_active_cost_gate()
    try:
      from app.services.content_ai_outline_engine import parse_outline_sections

      outline = str(payload.get("outline_content") or "")
      use_section_writer = len(parse_outline_sections(outline)) >= 2

      if use_section_writer:
        result = _run_section_writer(
          gid, user, payload, llm_gate, prompt_wc, gate_snapshot, hold
        )
      else:
        result = _run_live_stream(
          gid, user, payload, llm_gate, prompt_wc, gate_snapshot, hold
        )

      if result.get("cancelled"):
        if hold is not None and not hold._done:
          hold.release(reason="cancelled")
          db.commit()
        return result

      if not result.get("ok"):
        if hold is not None and not hold._done:
          hold.release(reason="generation_failed")
          db.commit()
        fail_generation(gid, error=str(result.get("error") or "generation_failed"))
        append_event(gid, "error", {"ok": False, "message": str(result.get("error") or "failed")[:800]})
        return result

      credits = 0
      if hold is not None and not hold._done:
        hold.commit()
        credits = int(hold.amount or 0)
        db.commit()
      elif llm_gate.get("charge_credits") and hold is None:
        charge_content_ai_write(db, user, quote, field=requested, llm_used=True, used_fallback=False)
        credits = int(quote.get("credit_cost") or llm_gate.get("unit_cost") or 0)
        db.commit()

      record_content_ai_usage(
        db,
        user,
        feature_key,
        quantity=1,
        metadata={"field": requested, "stream": True, "async": True},
      )
      db.commit()

      final = {
        "html": result.get("html") or "",
        "word_count_meta": result.get("word_count_meta") or {},
        "credits_charged": credits,
      }
      last_seq = append_event(gid, "done", True)
      complete_generation(gid, result=final, credits_charged=credits, last_stream_seq=last_seq)
      return {"ok": True, "generation_id": gid, "credits_charged": credits}
    finally:
      try:
        gate_cm.__exit__(None, None, None)
      except ValueError:
        set_active_cost_gate(None)
  except Exception as exc:
    _LOG.exception("content_ai generation failed generation_id=%s", gid)
    fail_generation(gid, error=str(exc)[:2000])
    append_event(gid, "error", {"ok": False, "message": str(exc)[:800]})
    return {"ok": False, "error": type(exc).__name__}
  finally:
    db.close()


def _run_section_writer(
  gid: str,
  user: User,
  payload: dict[str, Any],
  llm_gate: dict[str, Any],
  prompt_wc: Any,
  gate_snapshot: Any,
  hold: Any,
) -> dict[str, Any]:
  from app.services.content_ai_llm_providers import coerce_user_ai_provider
  from app.services.content_ai_word_count_policy import assess_word_count_meta
  from app.services.entitlement_service import resolve_effective_plan
  from app.services.llm_content_writer import generate_content_ai_suggestion
  from app.services.cost_control.context import set_active_cost_gate

  db = SessionLocal()
  try:
    plan_slug = resolve_effective_plan(db, user)
    ai_provider = coerce_user_ai_provider(payload.get("ai_provider"), plan_slug=plan_slug)
    requested = str(payload.get("field") or "content")
    if gate_snapshot is not None:
      set_active_cost_gate(gate_snapshot)
    html = str(
      generate_content_ai_suggestion(
        field="content",
        title=payload.get("title") or "",
        content=payload.get("content") or "",
        target_website=payload.get("target_website") or "",
        slug=payload.get("slug") or "",
        tags=payload.get("tags") or "",
        meta_description=payload.get("meta_description") or "",
        primary_keyword=payload.get("primary_keyword") or "",
        secondary_keywords=payload.get("secondary_keywords") or "",
        outline_content=payload.get("outline_content") or "",
        target_word_count=prompt_wc if requested == "content" else payload.get("target_word_count"),
        user_id=int(user.id),
        use_system_llm=bool(llm_gate.get("use_system_llm")),
        ai_provider=ai_provider,
        output_language=payload.get("output_language"),
      )
      or ""
    ).strip()
    if not html:
      return {"ok": False, "error": "llm_empty_content_html"}
    if _check_cancelled(gid):
      return {"ok": False, "cancelled": True}
    append_event(gid, "replace_html", html)
    wc_meta = {}
    wc_target = prompt_wc if requested == "content" else payload.get("target_word_count")
    if wc_target is not None:
      wc_meta = assess_word_count_meta(html, int(wc_target))
      append_event(gid, "word_count", wc_meta)
    update_generation_progress(gid, progress=95, message="Finalizing")
    return {"ok": True, "html": html, "word_count_meta": wc_meta}
  finally:
    db.close()


def _run_live_stream(
  gid: str,
  user: User,
  payload: dict[str, Any],
  llm_gate: dict[str, Any],
  prompt_wc: Any,
  gate_snapshot: Any,
  hold: Any,
) -> dict[str, Any]:
  from app.services.content_ai_knowledge_context import ContentAiLlmUnavailableError
  from app.services.cost_control.context import set_active_cost_gate
  from app.services.llm_content_writer import (
    finalize_content_ai_stream_html,
    iter_content_ai_content_stream_deltas,
  )

  requested = str(payload.get("field") or "content")
  stream_acc: list[str] = []
  any_delta = False
  if gate_snapshot is not None:
    set_active_cost_gate(gate_snapshot)
  for delta in iter_content_ai_content_stream_deltas(
    title=payload.get("title") or "",
    content=payload.get("content") or "",
    target_website=payload.get("target_website") or "",
    slug=payload.get("slug") or "",
    tags=payload.get("tags") or "",
    meta_description=payload.get("meta_description") or "",
    primary_keyword=payload.get("primary_keyword") or "",
    secondary_keywords=payload.get("secondary_keywords") or "",
    outline_content=payload.get("outline_content") or "",
    target_word_count=prompt_wc if requested == "content" else payload.get("target_word_count"),
    user_id=int(user.id),
    use_system_llm=bool(llm_gate.get("use_system_llm")),
    output_language=payload.get("output_language"),
  ):
    if _check_cancelled(gid):
      return {"ok": False, "cancelled": True}
    if gate_snapshot is not None:
      set_active_cost_gate(gate_snapshot)
    if not str(delta or ""):
      continue
    any_delta = True
    stream_acc.append(str(delta))
    append_event(gid, "delta", str(delta))
    update_generation_progress(gid, progress=min(90, 10 + len(stream_acc) // 5), message="Streaming")

  if not any_delta:
    return {"ok": False, "error": "llm_stream_empty"}

  raw_html = "".join(stream_acc)
  if gate_snapshot is not None:
    set_active_cost_gate(gate_snapshot)
  final_html, wc_meta = finalize_content_ai_stream_html(
    raw_html,
    target_word_count=prompt_wc if requested == "content" else payload.get("target_word_count"),
    title=payload.get("title") or "",
    primary_keyword=payload.get("primary_keyword") or "",
    outline_content=payload.get("outline_content") or "",
    target_website=payload.get("target_website") or "",
    use_system_llm=bool(llm_gate.get("use_system_llm")),
    user_id=int(user.id),
  )
  if str(final_html or "").strip() and str(final_html).strip() != str(raw_html).strip():
    append_event(gid, "replace_html", str(final_html))
  if wc_meta:
    append_event(gid, "word_count", wc_meta)
  return {"ok": True, "html": str(final_html or raw_html), "word_count_meta": wc_meta or {}}
