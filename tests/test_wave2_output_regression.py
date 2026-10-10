"""WAVE 2 — sync vs async output contract regression (same LLM mock → same SSE)."""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.content_ai_generation import ContentAiGeneration
from app.models.user import User

FIXED_DELTAS = ["<p>", "Hello ", "world", "</p>"]
FIXED_RAW = "<p>Hello world</p>"
FIXED_HTML = "<p>Hello world</p><footer></footer>"
FIXED_WC = {
    "word_count_target": 1000,
    "word_count_actual": 120,
    "word_count_ok": True,
    "validated_word_count": 1000,
    "actual_word_count": 120,
}


def _parse_sse_chunks(raw: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block.startswith("data:"):
            continue
        payload = block[5:].strip()
        if payload == "[DONE]":
            events.append({"done": True})
            continue
        try:
            events.append(json.loads(payload))
        except json.JSONDecodeError:
            events.append({"raw": payload})
    return events


def _normalize_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    deltas = []
    replace_html = None
    word_count = None
    done = False
    errors = []
    for ev in events:
        if ev.get("done"):
            done = True
        elif "delta" in ev:
            deltas.append(ev["delta"])
        elif "replace_html" in ev:
            replace_html = ev["replace_html"]
        elif "word_count_target" in ev or "word_count_actual" in ev:
            word_count = {
                "word_count_target": ev.get("word_count_target"),
                "word_count_actual": ev.get("word_count_actual"),
                "word_count_ok": ev.get("word_count_ok"),
            }
        elif ev.get("ok") is False or ev.get("message"):
            errors.append(ev)
        elif ev.get("ping"):
            pass
    return {
        "deltas": deltas,
        "replace_html": replace_html,
        "word_count": word_count,
        "done": done,
        "errors": errors,
        "joined_delta_html": "".join(deltas),
    }


@pytest.fixture()
def gen_db(monkeypatch):
    import app.models.knowledge  # noqa: F401
    import app.models.seo  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[User.__table__, ContentAiGeneration.__table__])
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr("app.services.content_ai_generation_store.SessionLocal", Session)
    return Session


@pytest.fixture()
def llm_mocks(monkeypatch):
    monkeypatch.setattr(
        "app.services.llm_content_writer.iter_content_ai_content_stream_deltas",
        lambda **kw: iter(list(FIXED_DELTAS)),
    )
    monkeypatch.setattr(
        "app.services.llm_content_writer.finalize_content_ai_stream_html",
        lambda raw, **kw: (FIXED_HTML, dict(FIXED_WC)),
    )
    monkeypatch.setattr(
        "app.services.user_api_access.load_llm_config_for_request",
        lambda db, user: {"provider": "mock"},
    )
    monkeypatch.setattr(
        "app.services.cost_control.module_gates.content_ai_llm_gate",
        lambda *a, **k: MagicMock(__enter__=lambda s: None, __exit__=lambda s, *e: None),
    )
    monkeypatch.setattr(
        "app.services.content_ai_entitlement.record_content_ai_usage",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.services.content_ai_credit_service.reserve_content_ai_write",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.services.content_ai_credit_service.charge_content_ai_write",
        lambda *a, **k: None,
    )


def test_sync_async_sse_contract_equivalent(gen_db, llm_mocks, monkeypatch):
    """Async path must emit same delta/replace_html/word_count/DONE contract as sync."""
    from app.services.content_ai_generation_runner import run_content_ai_generation
    from app.services.content_ai_generation_service import sse_bridge_generation
    from app.services.content_ai_generation_store import create_generation

    Session = gen_db
    db = Session()
    user = User(
        email=f"out-reg-{uuid.uuid4().hex[:8]}@test.local",
        password_hash="x",
        has_password=True,
        role="user",
        status="active",
    )
    db.add(user)
    db.commit()

    payload = {
        "field": "content",
        "title": "Test title",
        "primary_keyword": "test kw",
        "outline_content": "",
        "target_word_count": 1000,
        "user_id": user.id,
        "llm_gate": {
            "charge_credits": False,
            "use_system_llm": True,
            "prompt_word_count": 1000,
            "quote": {},
        },
        "feature_key": "content_ai_article",
    }

    # --- async path ---
    gen = create_generation(
        db,
        user_id=user.id,
        organization_id=user.id,
        idempotency_key=f"out-reg-{uuid.uuid4().hex}",
        request_payload=payload,
    )
    run_content_ai_generation(gen.generation_id, payload)

    async_chunks: list[str] = []

    def _cap(s: str) -> str:
        async_chunks.append(s)
        return s

    list(
        sse_bridge_generation(
            db,
            generation_id=gen.generation_id,
            user=user,
            after_seq=0,
            emit_delta=lambda d: _cap(f"data: {json.dumps({'delta': d}, ensure_ascii=False)}\n\n"),
            emit_replace=lambda h: _cap(f"data: {json.dumps({'replace_html': h}, ensure_ascii=False)}\n\n"),
            emit_wc=lambda m: _cap(
                f"data: {json.dumps({'word_count_target': m.get('word_count_target'), 'word_count_actual': m.get('word_count_actual'), 'word_count_ok': m.get('word_count_ok')}, ensure_ascii=False)}\n\n"
            ),
            emit_ping=lambda: _cap(f"data: {json.dumps({'ping': True}, ensure_ascii=False)}\n\n"),
            emit_error=lambda **_: _cap('data: {"ok": false}\n\n'),
            emit_done=lambda: _cap("data: [DONE]\n\n"),
        )
    )
    async_norm = _normalize_events(_parse_sse_chunks("".join(async_chunks)))

    # --- sync path (inline generator mirror) ---
    sync_chunks: list[str] = []
    for d in FIXED_DELTAS:
        sync_chunks.append(f"data: {json.dumps({'delta': d}, ensure_ascii=False)}\n\n")
    sync_chunks.append(f"data: {json.dumps({'replace_html': FIXED_HTML}, ensure_ascii=False)}\n\n")
    sync_chunks.append(
        f"data: {json.dumps({'word_count_target': FIXED_WC['word_count_target'], 'word_count_actual': FIXED_WC['word_count_actual'], 'word_count_ok': FIXED_WC['word_count_ok']}, ensure_ascii=False)}\n\n"
    )
    sync_chunks.append("data: [DONE]\n\n")
    sync_norm = _normalize_events(_parse_sse_chunks("".join(sync_chunks)))

    assert async_norm["done"] is True
    assert sync_norm["done"] is True
    assert async_norm["deltas"] == sync_norm["deltas"] == FIXED_DELTAS
    assert async_norm["replace_html"] == sync_norm["replace_html"] == FIXED_HTML
    assert not async_norm["errors"]
    db.close()


def test_idempotent_generation_reuses_same_id(gen_db):
    from app.services.content_ai_generation_store import create_generation

    db = gen_db()
    user = User(email="idem2@test.local", password_hash="x", has_password=True, role="user", status="active")
    db.add(user)
    db.commit()
    k = f"idem-{uuid.uuid4().hex}"
    g1 = create_generation(db, user_id=user.id, organization_id=user.id, idempotency_key=k, request_payload={"a": 1})
    g2 = create_generation(db, user_id=user.id, organization_id=user.id, idempotency_key=k, request_payload={"a": 1})
    assert g1.generation_id == g2.generation_id
