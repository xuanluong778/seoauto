"""Tests for Chat tab mode — suggest workflow tabs, no auto-run."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.chatbot_chat_mode import (
    build_chat_mode_workflow_reply,
    chat_mode_workflow_response,
    detect_workflow_tab_suggestion,
)
from app.services.chatbot_command_parser import parse_chatbot_command
from app.services.chatbot_service import process_message
from app.services.chatbot_tab_registry import TAB_WRITE, TAB_TECHNICAL, TAB_RESEARCH


def test_detect_write_tab_from_text():
    hit = detect_workflow_tab_suggestion("Gom nhóm từ khóa SEO và viết bài 1500 từ")
    assert hit is not None
    assert hit[0] == TAB_WRITE


def test_detect_technical_tab_from_text():
    hit = detect_workflow_tab_suggestion("Audit technical website example.com giúp tôi")
    assert hit is not None
    assert hit[0] == TAB_TECHNICAL


def test_chat_mode_workflow_response_has_suggest_tab():
    wf = parse_chatbot_command("Research từ khóa laptop gaming mở rộng liên quan")
    out = chat_mode_workflow_response(
        message="Research từ khóa laptop gaming mở rộng liên quan",
        workflow=wf,
        session_id="sess_test",
        page_context="home",
    )
    assert out is not None
    assert out["suggest_tab"] in (TAB_RESEARCH, TAB_WRITE)
    assert "Chat" in out["reply"] or "chat" in out["reply"].lower() or "credit" in out["reply"]
    assert out.get("workflow") is None


def test_build_chat_mode_reply_mentions_tab():
    msg = build_chat_mode_workflow_reply(TAB_WRITE, "Viết bài SEO")
    assert "Viết bài SEO" in msg
    assert "credit" in msg.lower()


@patch("app.services.chatbot_service.append_history")
@patch("app.services.chatbot_service.check_rate_limit", return_value=True)
@patch("app.services.chatbot_service.get_or_create_session", return_value="s1")
@patch("app.services.chatbot_service.detect_page_context", return_value="home")
@patch("app.services.chatbot_service.parse_chatbot_command")
def test_process_message_chat_mode_skips_workflow_run(mock_parse, _ctx, _sess, _rate, _hist):
    from app.services.chatbot_command_parser import WorkflowParseResult

    mock_parse.return_value = WorkflowParseResult(
        intent="keyword_cluster_to_article",
        primary_keyword="seo",
        word_count=1500,
        image_source="none",
    )
    out = process_message(
        message="Viết bài SEO từ khóa marketing",
        history=[],
        chat_mode=True,
        user_id=1,
    )
    assert out.get("suggest_tab") == TAB_WRITE
    assert "workflow" not in out or out.get("workflow") is None


@patch("app.services.chatbot_service.append_history")
@patch("app.services.chatbot_service.check_rate_limit", return_value=True)
@patch("app.services.chatbot_service.get_or_create_session", return_value="s1")
@patch("app.services.chatbot_service.detect_page_context", return_value="home")
@patch("app.services.chatbot_service.resolve_pricing_reply", return_value=None)
@patch("app.services.chatbot_service.match_faq", return_value="FAQ trả lời")
@patch("app.services.chatbot_service.parse_chatbot_command")
def test_process_message_chat_mode_faq(mock_parse, _faq, _price, _ctx, _sess, _rate, _hist):
    from app.services.chatbot_command_parser import WorkflowParseResult

    mock_parse.return_value = WorkflowParseResult()
    out = process_message(message="Giá gói Pro bao nhiêu?", history=[], chat_mode=True)
    assert out["reply"] == "FAQ trả lời"
    assert out.get("chat_mode") is True
