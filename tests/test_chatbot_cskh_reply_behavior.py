"""Unit tests for Chatbot CSKH lead intent + soft no-data behavior."""

from __future__ import annotations

from app.services.chatbot_cskh_entitlement import NO_DATA_REPLY
from app.services.chatbot_cskh_lead_detect import detect_lead_intent
from app.services.chatbot_cskh_ai_service import (
    _score_haystack,
    _should_offer_lead,
    _tokenize,
)


def test_no_data_reply_does_not_ask_for_phone():
    assert "số điện thoại" not in NO_DATA_REPLY.lower()
    assert "sđt" not in NO_DATA_REPLY.lower()


def test_service_question_does_not_trigger_lead():
    intent = detect_lead_intent("có sửa máy in không?")
    assert intent["should_offer_lead"] is False
    offer, _ = _should_offer_lead("có sửa máy in không?", no_data=False)
    assert offer is False
    offer_no_data, _ = _should_offer_lead("có sửa máy in không?", no_data=True)
    assert offer_no_data is False


def test_price_and_consult_trigger_lead():
    assert detect_lead_intent("giá bao nhiêu?")["should_offer_lead"] is True
    assert detect_lead_intent("gọi tư vấn cho tôi")["should_offer_lead"] is True
    assert detect_lead_intent("đặt lịch sửa máy")["should_offer_lead"] is True
    assert detect_lead_intent("cho mình xin hotline")["should_offer_lead"] is True


def test_tokenize_keeps_service_terms():
    tokens = _tokenize("có sửa máy in không?")
    assert "sửa" in tokens
    assert "máy" in tokens
    assert "in" in tokens


def test_score_matches_service_content():
    hay = "dịch vụ sửa máy in laser, đổ mực, bảo trì định kỳ"
    tokens = _tokenize("có sửa máy in không?")
    score = _score_haystack(hay, tokens, title="Sửa máy in")
    assert score >= 3
