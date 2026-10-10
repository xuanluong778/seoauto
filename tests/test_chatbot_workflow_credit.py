"""Tests for chatbot workflow credit service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.chatbot_workflow_credit import (
    CREDIT_STATUS_CANCELLED,
    CREDIT_STATUS_CHARGED,
    CREDIT_STATUS_REFUNDED,
    CREDIT_STATUS_RUNNING,
    InsufficientCreditError,
    create_credit_log,
    format_credit_estimate_message,
    format_insufficient_credit_message,
    quote_workflow_credits,
    refund_workflow_credits,
    update_credit_log,
)


def test_format_credit_messages():
    assert format_credit_estimate_message(13) == "Tác vụ này dự kiến tốn 13 credit."
    assert (
        format_insufficient_credit_message(18, 2)
        == "Bạn cần 18 credit, tài khoản hiện có 2 credit."
    )


def test_insufficient_credit_error():
    err = InsufficientCreditError(required=10, balance=3)
    assert err.required == 10
    assert err.balance == 3
    assert "10" in err.message
    assert "3" in err.message


@patch("app.services.entitlement_service.can_use_ai", return_value={"allowed": True})
@patch("app.services.software_access_service.user_has_software_access", return_value=True)
@patch("app.services.chatbot_workflow_credit.estimate_workflow_credits")
@patch("app.services.chatbot_workflow_credit.ensure_sufficient_credits", return_value=(50, True))
@patch("app.services.chatbot_workflow_credit.credits_enforced", return_value=True)
def test_quote_workflow_credits_sufficient(_enf, _suff, mock_est, _access, _ai):
    mock_est.return_value = {"total": 8, "research": 5, "clustering": 3}
    db = MagicMock()
    db.get.return_value = MagicMock(id=1, role="user")
    quote = quote_workflow_credits(db, 1, "keyword_research", {"seed_keyword": "seo"})
    assert quote["credit_required"] == 8
    assert quote["credit_balance"] == 50
    assert quote["sufficient"] is True
    assert quote["credit_estimate_message"] == "Tác vụ này dự kiến tốn 8 credit."
    assert quote["insufficient_message"] is None


@patch("app.services.entitlement_service.can_use_ai", return_value={"allowed": False, "message": "Bạn cần 18 credit, tài khoản hiện có 2 credit."})
@patch("app.services.software_access_service.user_has_software_access", return_value=True)
@patch("app.services.chatbot_workflow_credit.estimate_workflow_credits")
@patch("app.services.chatbot_workflow_credit.ensure_sufficient_credits", return_value=(2, False))
@patch("app.services.chatbot_workflow_credit.credits_enforced", return_value=True)
def test_quote_workflow_credits_insufficient(_enf, _suff, mock_est, _access, _ai):
    mock_est.return_value = {"total": 18}
    db = MagicMock()
    db.get.return_value = MagicMock(id=1, role="user")
    quote = quote_workflow_credits(db, 1, "keyword_research", {})
    assert quote["sufficient"] is False
    assert quote["insufficient_message"] == "Bạn cần 18 credit, tài khoản hiện có 2 credit."


def test_create_and_update_credit_log():
    db = MagicMock()
    with patch("app.services.chatbot_workflow_credit.ChatbotWorkflowCreditLog") as mock_cls:
        inst = MagicMock()
        mock_cls.return_value = inst
        row = create_credit_log(
            db,
            user_id=7,
            workflow="keyword_research",
            task_id="wf_test_1",
            credit_used=5,
            status="pending",
        )
        assert row is inst
        mock_cls.assert_called_once()
        db.add.assert_called_once_with(inst)
        db.flush.assert_called_once()

    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = inst
    update_credit_log(
        db,
        task_id="wf_test_1",
        status=CREDIT_STATUS_CHARGED,
        credit_used=5,
    )
    assert inst.status == CREDIT_STATUS_CHARGED

    update_credit_log(
        db,
        task_id="wf_test_1",
        status=CREDIT_STATUS_CANCELLED,
        credit_used=0,
        error_reason="Không đủ credit",
    )
    assert inst.status == CREDIT_STATUS_CANCELLED
    assert inst.credit_used == 0
    assert inst.error_reason == "Không đủ credit"


@patch("app.services.rbac.is_admin", return_value=False)
@patch("app.services.credits.grant_credits")
@patch("app.services.credits.credits_enforced", return_value=True)
def test_refund_workflow_credits_on_failure(_enf, mock_grant, _admin):
    db = MagicMock()
    row = MagicMock()
    row.status = CREDIT_STATUS_CHARGED
    row.credit_used = 44
    row.error_reason = None
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = row
    db.get.return_value = MagicMock(id=1)

    refunded = refund_workflow_credits(
        db,
        user_id=7,
        task_id="wf_fail_1",
        reason="Không sinh được bài đủ số từ",
    )
    assert refunded == 44
    mock_grant.assert_called_once()
    assert row.status == CREDIT_STATUS_REFUNDED
    assert row.credit_used == 0


@patch("app.services.credits.grant_credits")
@patch("app.services.chatbot_workflow_credit.credits_enforced", return_value=True)
def test_refund_workflow_credits_idempotent(_enf, mock_grant):
    db = MagicMock()
    row = MagicMock()
    row.status = CREDIT_STATUS_REFUNDED
    row.credit_used = 0
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = row

    refunded = refund_workflow_credits(db, user_id=7, task_id="wf_fail_2", reason="x")
    assert refunded == 0
    mock_grant.assert_not_called()


@patch("app.services.credits.grant_credits")
@patch("app.services.chatbot_workflow_credit.credits_enforced", return_value=True)
def test_refund_skipped_when_completed(_enf, mock_grant):
    db = MagicMock()
    row = MagicMock()
    row.status = "completed"
    row.credit_used = 44
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = row

    refunded = refund_workflow_credits(db, user_id=7, task_id="wf_ok_1", reason="x")
    assert refunded == 0
    mock_grant.assert_not_called()
