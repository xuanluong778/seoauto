"""Lead/contact extraction for Chatbot CSKH."""

from __future__ import annotations

from app.services.chatbot_cskh_lead_detect import (
    contact_ack_reply,
    detect_lead_from_text,
    detect_lead_intent,
    extract_email,
    extract_phone,
    is_mostly_contact_message,
)
from app.services.chatbot_cskh_ai_service import _should_offer_lead


def test_extract_phone_plain():
    assert extract_phone("0976086500") == "0976086500"


def test_extract_phone_with_spaces():
    assert extract_phone("SĐT của tôi: 0976 086 500") == "0976086500"


def test_extract_phone_plus84():
    assert extract_phone("+84 976 086 500") == "0976086500"


def test_extract_gmail():
    assert extract_email("mail tôi là abc@gmail.com nhé") == "abc@gmail.com"


def test_extract_generic_email():
    assert extract_email("liên hệ qua sales@thegioidigi.com") == "sales@thegioidigi.com"


def test_detect_lead_from_email_only():
    out = detect_lead_from_text("abc@gmail.com")
    assert out["email"] == "abc@gmail.com"
    assert out["has_lead_signal"] is True
    assert out["has_contact_info"] is True


def test_detect_lead_from_phone_and_email():
    out = detect_lead_from_text("0976086500 hoặc abc@gmail.com")
    assert out["phone"] == "0976086500"
    assert out["email"] == "abc@gmail.com"


def test_contact_intent_from_phone_message():
    intent = detect_lead_intent("0976086500")
    assert intent["should_offer_lead"] is True
    assert "contact_provided" in intent["intents"]


def test_contact_intent_from_gmail_message():
    intent = detect_lead_intent("gmail: abc@gmail.com")
    assert intent["should_offer_lead"] is True


def test_should_offer_lead_for_contact_even_without_faq_intent():
    offer, _ = _should_offer_lead("0976086500", no_data=True)
    assert offer is True


def test_mostly_contact_message():
    detected = detect_lead_from_text("0976086500")
    assert is_mostly_contact_message("0976086500", detected) is True


def test_contact_ack_reply():
    reply = contact_ack_reply({"phone": "0976086500", "email": "abc@gmail.com"})
    assert "0976086500" in reply
    assert "abc@gmail.com" in reply
