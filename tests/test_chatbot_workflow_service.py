"""Tests for chatbot workflow service (credit confirm + start)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.chatbot_command_parser import parse_chatbot_command
from app.services.chatbot_workflow_credit import format_insufficient_credit_message
from app.services.chatbot_workflow_service import (
    handle_workflow_intent,
    prepare_workflow_confirmation,
    start_workflow,
)
from app.services.chatbot_workflow_store import get_workflow_for_user


@pytest.fixture(autouse=True)
def _grant_saas_access(monkeypatch):
    monkeypatch.setattr("app.services.saas_gate.user_has_software_access", lambda db, uid: True)
    monkeypatch.setattr("app.services.software_access_service.user_has_software_access", lambda db, uid: True)


@pytest.fixture
def db_session():
    return MagicMock()


@patch("app.services.chatbot_workflow_service.quote_workflow_credits")
def test_prepare_confirmation_includes_credits(mock_quote, db_session):
    mock_quote.return_value = {
        "credits": {
            "research": 5,
            "clustering": 3,
            "content_ai": 5,
            "internal_links": 0,
            "images": 0,
            "total": 13,
        },
        "credit_required": 13,
        "credit_balance": 100,
        "balance": 100,
        "sufficient": True,
        "credit_estimate_message": "Tác vụ này dự kiến tốn 13 credit.",
        "insufficient_message": None,
    }
    wf = parse_chatbot_command("Gom nhóm từ khóa đào tạo SEO và viết bài 1200 từ cho tôi")
    reply, payload = prepare_workflow_confirmation(
        db_session, user_id=7, session_id="sess_x", workflow=wf
    )
    assert payload["phase"] == "pending_confirm"
    assert payload["credits"]["total"] == 13
    assert payload["workflow_id"]
    assert "credit" in reply.lower()
    assert any(a.get("label") == "Tiếp tục" for a in payload.get("actions") or [])


@patch("app.services.chatbot_workflow_service.quote_workflow_credits")
def test_insufficient_credit_denied(mock_quote, db_session):
    mock_quote.return_value = {
        "credits": {
            "research": 5,
            "clustering": 3,
            "content_ai": 5,
            "internal_links": 2,
            "images": 3,
            "total": 18,
        },
        "credit_required": 18,
        "credit_balance": 2,
        "balance": 2,
        "sufficient": False,
        "credit_estimate_message": "Tác vụ này dự kiến tốn 18 credit.",
        "insufficient_message": format_insufficient_credit_message(18, 2),
    }
    wf = parse_chatbot_command("Research từ khóa CRM rồi viết bài SEO 1500 từ")
    reply, payload = prepare_workflow_confirmation(
        db_session, user_id=7, session_id="sess_y", workflow=wf
    )
    assert payload["phase"] == "denied"
    assert "Bạn cần 18 credit" in reply
    assert "2 credit" in reply


def test_guest_cannot_start_workflow(db_session):
    wf = parse_chatbot_command("Gom nhóm từ khóa SEO và viết bài")
    reply, payload = handle_workflow_intent(
        db_session, user_id=None, session_id="s1", workflow=wf
    )
    assert payload.get("phase") == "guest_denied"
    assert "đăng nhập" in reply.lower()


@patch("app.services.chatbot_workflow_service.create_credit_log")
@patch("app.services.chatbot_workflow_service.consume_workflow_credits")
@patch("app.services.chatbot_workflow_service.quote_workflow_credits")
def test_start_workflow_sets_running(mock_quote, mock_consume, _create_log, db_session):
    mock_quote.return_value = {
        "credits": {
            "research": 5,
            "clustering": 3,
            "content_ai": 5,
            "internal_links": 0,
            "images": 0,
            "total": 13,
        },
        "credit_required": 13,
        "credit_balance": 100,
        "balance": 100,
        "sufficient": True,
        "credit_estimate_message": "Tác vụ này dự kiến tốn 13 credit.",
        "insufficient_message": None,
    }
    wf = parse_chatbot_command("Gom nhóm từ khóa laptop gaming và viết bài 1000 từ")
    _, payload = prepare_workflow_confirmation(
        db_session, user_id=9, session_id="sess_z", workflow=wf
    )
    wf_id = payload["workflow_id"]
    mock_consume.return_value = {"charged": True, "total": 13}

    with patch("app.services.chatbot_workflow_service.threading.Thread") as mock_thread:
        mock_thread.return_value.start = MagicMock()
        rec = start_workflow(db_session, user_id=9, workflow_id=wf_id)

    assert rec.phase == "running"
    mock_consume.assert_called_once()
    db_session.commit.assert_called()
    stored = get_workflow_for_user(wf_id, 9)
    assert stored and stored.phase == "running"


def test_start_workflow_wrong_user():
    wf = parse_chatbot_command("Gom nhóm từ khóa test và viết bài 1200 từ")
    db = MagicMock()
    with patch("app.services.chatbot_workflow_service.quote_workflow_credits") as mock_quote:
        mock_quote.return_value = {
            "credits": {"total": 0},
            "credit_required": 0,
            "credit_balance": 999,
            "balance": 999,
            "sufficient": True,
            "credit_estimate_message": "Tác vụ này dự kiến tốn 0 credit.",
            "insufficient_message": None,
        }
        _, payload = prepare_workflow_confirmation(
            db, user_id=1, session_id="s", workflow=wf
        )
    with pytest.raises(PermissionError):
        start_workflow(MagicMock(), user_id=999, workflow_id=payload["workflow_id"])
