from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.email_automation_marketing import (
    AUTOMATION_EMAIL_TYPES,
    CAMPAIGN_STATUS_CANCELLED,
    EmailMarketingCampaign,
    EmailSend,
)
from app.services.email_html_sanitize import (
    is_safe_http_url,
    sanitize_email_html,
    validate_image_url,
    validate_link_url,
)
from app.services.email_automation_marketing_engine import render_email_preview
from app.services.email_ai_composer import compose_email
from app.workers import email_automation_marketing_worker as worker_mod
from tests.test_email_automation_marketing import (  # noqa: F401
    _create_plan,
    _create_subscription,
    _create_user,
)

pytest_plugins = ["tests.test_email_automation_marketing"]


def test_sanitize_strips_xss_and_keeps_cta():
    dirty = '<p>Hi {{name}}</p><script>alert(1)</script><a href="javascript:alert(1)">x</a>'
    dirty += '<a href="https://seoauto.vn/ok">ok</a><img src="https://cdn.example.com/a.png" onerror="alert(1)">'
    clean = sanitize_email_html(dirty)
    assert "<script" not in clean.lower()
    assert "javascript:" not in clean.lower()
    assert "onerror" not in clean.lower()
    assert "{{name}}" in clean
    assert "https://seoauto.vn/ok" in clean
    assert "https://cdn.example.com/a.png" in clean


def test_url_validation():
    assert is_safe_http_url("https://seoauto.vn/account-billing")
    assert is_safe_http_url("{{cta_url}}")
    with pytest.raises(ValueError):
        validate_link_url("javascript:alert(1)")
    with pytest.raises(ValueError):
        validate_image_url("mailto:a@b.c")


def test_personalization_preview_credit_balance():
    out = render_email_preview(
        subject="Hi {{name}} — {{plan}}",
        html_body="<p>Credit: {{credit_balance}} hết hạn {{expiry_date}}</p>",
        text_body=None,
        preheader="Xin chào {{name}}",
        cta_label="Mở",
        cta_url="https://seoauto.vn/x",
    )
    assert "Nguyễn Văn A" in out["subject"]
    assert "{{" not in out["subject"]
    assert "120" in out["html"]
    assert "2026-12-31" in out["html"]
    assert "Huỷ đăng ký" in out["html"] or "unsubscribe" in out["html"].lower()


def test_ai_composer_generate_and_rewrite(monkeypatch):
    calls = []

    def _fake_chat(**kwargs):
        calls.append(kwargs)
        return '{"subject":"Gia hạn {{plan}}","preheader":"Còn ít ngày","html_body":"<p>Chào {{name}}</p><script>x</script>","text_body":"Chào {{name}}"}'

    monkeypatch.setattr("app.services.llm_content_writer.load_llm_config", lambda user_id=None: None)
    monkeypatch.setattr(
        "app.services.llm_content_writer.load_llm_config_admin",
        lambda: type("C", (), {"provider": "openai", "logical_provider": "openai"})(),
    )
    monkeypatch.setattr("app.services.llm_content_writer._llm_chat_for_cfg", _fake_chat)

    gen = compose_email(action="generate", goal="nhắc gia hạn", segment="active", cta_label="Gia hạn", cta_url="https://seoauto.vn/")
    assert gen["subject"]
    assert "<script" not in gen["html_body"].lower()
    assert "{{name}}" in gen["html_body"]
    rw = compose_email(action="shorter", current_html="<p>dài</p>")
    assert rw["text_body"]
    assert len(calls) == 2


def test_low_credit_segment_and_no_duplicate(db, monkeypatch):
    session, _engine = db
    sent: list[str] = []
    monkeypatch.setattr(
        worker_mod,
        "send_email",
        lambda **kw: sent.append(kw["to"]) or {"ok": True, "provider": "stub"},
        raising=True,
    )
    admin = _create_user(session, email="adm-lc@test.local")
    p = _create_plan(session, slug="planLC", name="Plan LC")
    low = _create_user(session, email="low@test.local")
    rich = _create_user(session, email="rich@test.local")
    low.credit_balance = 10
    rich.credit_balance = 500
    now = datetime.now(timezone.utc)
    _create_subscription(session, user_id=low.id, plan_id=p.id, status="active", end_dt=now + timedelta(days=10))
    _create_subscription(session, user_id=rich.id, plan_id=p.id, status="active", end_dt=now + timedelta(days=10))
    session.commit()

    camp = EmailMarketingCampaign(
        owner_user_id=admin.id,
        name="Low",
        subject="Hi {{name}} cr {{credit_balance}}",
        html_body="<p>{{credit_balance}}</p>",
        cta_label="Go",
        cta_url="https://seoauto.vn/account-billing",
        segment_kind="low_credit",
        send_mode="now",
        status="scheduled",
    )
    session.add(camp)
    session.commit()

    out = worker_mod.email_marketing_send_campaign_task.run(int(camp.id))
    assert out["ok"] is True
    assert sent == [low.email.lower()]

    # Second send must not duplicate (unique campaign+email)
    camp.status = "scheduled"
    session.commit()
    sent.clear()
    out2 = worker_mod.email_marketing_send_campaign_task.run(int(camp.id))
    assert out2["ok"] is True
    assert sent == []

    row = session.query(EmailSend).filter(EmailSend.campaign_id == camp.id).one()
    assert row.recipient_email == low.email.lower()


def test_cancel_skips_send(db, monkeypatch):
    session, _engine = db
    sent: list[str] = []
    monkeypatch.setattr(worker_mod, "send_email", lambda **kw: sent.append("x") or {"ok": True, "provider": "stub"}, raising=True)
    admin = _create_user(session, email="adm-c@test.local")
    camp = EmailMarketingCampaign(
        owner_user_id=admin.id,
        name="C",
        subject="S",
        html_body="<p>x</p>",
        cta_label="Go",
        cta_url="https://seoauto.vn/",
        segment_kind="all",
        send_mode="now",
        status=CAMPAIGN_STATUS_CANCELLED,
    )
    session.add(camp)
    session.commit()
    out = worker_mod.email_marketing_send_campaign_task.run(int(camp.id))
    assert out.get("reason") == "cancelled"
    assert sent == []


def test_extended_automation_types_exist():
    for t in ("welcome", "trial_ending", "low_credit", "payment_success", "payment_fail", "inactive_user", "expired"):
        assert t in AUTOMATION_EMAIL_TYPES


def test_list_segment_recipients_expired(db):
    from datetime import datetime, timedelta, timezone
    from app.services.email_automation_marketing_engine import list_segment_recipients

    session, _engine = db
    active_u = _create_user(session, email="seg-active@test.local")
    expired_u = _create_user(session, email="seg-expired@test.local")
    plan = _create_plan(session, slug="seg-plan", name="SegPlan")
    now = datetime.now(timezone.utc)
    _create_subscription(
        session,
        user_id=active_u.id,
        plan_id=plan.id,
        status="active",
        end_dt=now + timedelta(days=10),
    )
    _create_subscription(
        session,
        user_id=expired_u.id,
        plan_id=plan.id,
        status="expired",
        end_dt=now - timedelta(days=2),
    )
    session.commit()
    rows = list_segment_recipients(session, segment_kind="expired", limit=100)
    emails = {r["email"] for r in rows}
    assert "seg-expired@test.local" in emails
    assert "seg-active@test.local" not in emails


def test_email_ai_composer_gate_allows_openai_call(db, monkeypatch):
    """Regression: compose must open cost gate or execute_guarded_external 500s."""
    from app.services.cost_control.executor import CostControlBypassError, execute_guarded_external
    from app.services.cost_control.module_gates import email_ai_composer_gate
    from app.services.cost_control.types import ExternalApiProvider

    session, _engine = db
    admin = _create_user(session, email="adm-email-ai-gate@test.local")
    admin.role = "admin"
    session.commit()

    monkeypatch.setattr("app.services.cost_control.executor.cost_control_enforced", lambda: True)
    monkeypatch.setattr("app.services.cost_control.gate.cost_control_enforced", lambda: True)
    monkeypatch.setattr("app.services.cost_control.gate.is_admin", lambda _u: True)
    monkeypatch.setattr("app.services.rbac.is_admin", lambda _u: True)

    with pytest.raises(CostControlBypassError):
        execute_guarded_external(ExternalApiProvider.OPENAI, "chat_completion", lambda: "blocked")

    with email_ai_composer_gate(session, admin, action="chat_completion"):
        assert execute_guarded_external(ExternalApiProvider.OPENAI, "chat_completion", lambda: "ok") == "ok"
