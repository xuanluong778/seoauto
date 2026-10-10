"""Chatbot CSKH — lead extraction + clear lead-intent detection."""

from __future__ import annotations

import re
from typing import Any

# Vietnamese mobile: 0/84 + optional separators + 9 digits (3|5|7|8|9 prefix).
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?84|0)[\s.\-]*(?:3|5|7|8|9)[\s.\-]*(?:\d[\s.\-]*){8}(?!\d)",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(
    r"(?<![\w.+-])([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})(?![\w.-])",
    re.IGNORECASE,
)
_NAME_PATTERNS = (
    re.compile(r"(?:tên\s*(?:tôi|em|mình|của\s*tôi)\s*(?:là|:)\s*)([A-Za-zÀ-ỹ][A-Za-zÀ-ỹ\s]{1,40})", re.I),
    re.compile(r"(?:tôi\s+là|em\s+là|mình\s+là)\s+([A-Za-zÀ-ỹ][A-Za-zÀ-ỹ\s]{1,40})", re.I),
)
_NEED_PATTERNS = (
    re.compile(r"(?:cần|muốn|đang\s+tìm|quan\s+tâm)\s+(.{8,200})", re.I),
    re.compile(r"(?:tư\s+vấn|hỏi)\s+(?:về\s+)?(.{8,200})", re.I),
)
_CONTACT_NOISE = frozenset({
    "sdt", "sđt", "so", "dien", "thoai", "điện", "thoại", "phone", "tel", "mobile",
    "email", "gmail", "mail", "e", "cua", "của", "toi", "tôi", "em", "minh", "mình",
    "la", "là", "day", "đây", "nhe", "nhé", "xin", "cho", "gui", "gửi", "lien", "liên",
    "he", "hệ", "lac", "lạc", "contact", "zalo", "viber", "hotline", "skype",
})

# Clear commercial / contact intents only — not general FAQ.
_INTENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("price", re.compile(
        r"\b(giá|báo\s*giá|chi\s*phí|phí\s*bao\s*nhiêu|giá\s*bao\s*nhiêu|bao\s*nhiêu\s*tiền|"
        r"bảng\s*giá|giá\s*cả|cost|price)\b",
        re.I,
    )),
    ("booking", re.compile(
        r"\b(đặt\s*lịch|đặt\s*hẹn|book|booking|hẹn\s*lịch|đăng\s*ký\s*(dịch\s*vụ|lịch))\b",
        re.I,
    )),
    ("callback", re.compile(
        r"\b(gọi\s*(lại|cho\s*tôi|tư\s*vấn)|callback|liên\s*hệ\s*(lại|cho\s*tôi)|"
        r"nhờ\s*(gọi|liên\s*hệ)|muốn\s*được\s*gọi)\b",
        re.I,
    )),
    ("consult", re.compile(
        r"\b(tư\s*vấn|cần\s*tư\s*vấn|muốn\s*tư\s*vấn|hỗ\s*trợ\s*tư\s*vấn|"
        r"nhân\s*viên\s*(tư\s*vấn|hỗ\s*trợ)|cần\s*nhân\s*viên)\b",
        re.I,
    )),
    ("contact_info", re.compile(
        r"\b(số\s*điện\s*thoại|sđt|sdt|hotline|zalo|địa\s*chỉ|địa\s*điểm|"
        r"liên\s*hệ\s*(ở\s*đâu|như\s*thế\s*nào|qua)|phone|address|email|gmail|mail)\b",
        re.I,
    )),
    ("staff_help", re.compile(
        r"\b(gặp\s*nhân\s*viên|nói\s*chuyện\s*với\s*người|chuyển\s*(máy|nhân\s*viên)|"
        r"cần\s*hỗ\s*trợ\s*(trực\s*tiếp|từ\s*người)|live\s*agent)\b",
        re.I,
    )),
]


def _normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    if digits.startswith("84") and len(digits) >= 11:
        digits = "0" + digits[2:]
    if len(digits) == 9 and digits[0] in "35789":
        digits = "0" + digits
    return digits[:32] if len(digits) >= 10 else ""


def _normalize_email(raw: str) -> str:
    email = str(raw or "").strip().lower()
    if not email or "@" not in email:
        return ""
    if len(email) > 255:
        return ""
    return email


def extract_phone(text: str) -> str:
    for m in _PHONE_RE.finditer(str(text or "")):
        phone = _normalize_phone(m.group(0))
        if phone:
            return phone
    return ""


def extract_email(text: str) -> str:
    for m in _EMAIL_RE.finditer(str(text or "")):
        email = _normalize_email(m.group(1))
        if email:
            return email
    return ""


def extract_name(text: str) -> str:
    t = str(text or "").strip()
    for pat in _NAME_PATTERNS:
        m = pat.search(t)
        if m:
            name = str(m.group(1) or "").strip()
            if 2 <= len(name) <= 80:
                return name[:120]
    return ""


def extract_need(text: str) -> str:
    t = str(text or "").strip()
    for pat in _NEED_PATTERNS:
        m = pat.search(t)
        if m:
            need = str(m.group(1) or "").strip().rstrip(".,;")
            if len(need) >= 8:
                return need[:2000]
    phone = extract_phone(t)
    email = extract_email(t)
    if len(t) >= 15 and not phone and not email:
        return t[:2000]
    return ""


def has_contact_info(text: str) -> bool:
    detected = detect_lead_from_text(text)
    return bool(detected.get("phone") or detected.get("email"))


def is_mostly_contact_message(text: str, detected: dict[str, Any] | None = None) -> bool:
    """True when the message is primarily sharing phone/email contact details."""
    info = detected or detect_lead_from_text(text)
    phone = str(info.get("phone") or "")
    email = str(info.get("email") or "")
    if not phone and not email:
        return False

    remainder = str(text or "")
    if phone:
        remainder = re.sub(re.escape(phone), " ", remainder)
        remainder = re.sub(r"0[\s.\-]*" + re.escape(phone[1:]), " ", remainder)
    if email:
        remainder = re.sub(re.escape(email), " ", remainder, flags=re.I)
    remainder = re.sub(_PHONE_RE, " ", remainder)
    remainder = re.sub(_EMAIL_RE, " ", remainder)
    remainder = re.sub(r"[^\w\s]", " ", remainder.lower())
    words = [w for w in remainder.split() if w and w not in _CONTACT_NOISE]
    return len(" ".join(words)) <= 24


def contact_ack_reply(detected: dict[str, Any]) -> str:
    parts: list[str] = []
    if detected.get("phone"):
        parts.append(f"số điện thoại {detected['phone']}")
    if detected.get("email"):
        parts.append(f"email {detected['email']}")
    joined = " và ".join(parts)
    return f"Cảm ơn bạn! Chúng tôi đã ghi nhận {joined}. Nhân viên sẽ liên hệ bạn sớm nhất."


def detect_lead_from_text(text: str) -> dict[str, Any]:
    phone = extract_phone(text)
    email = extract_email(text)
    name = extract_name(text)
    need = extract_need(text) if phone or email or name else ""
    return {
        "phone": phone,
        "email": email,
        "name": name,
        "need": need,
        "has_lead_signal": bool(phone or email or (name and need)),
        "has_contact_info": bool(phone or email),
    }


def detect_lead_intent(text: str) -> dict[str, Any]:
    """
    Detect clear lead/contact intent from visitor message.
    General FAQ / service questions must NOT trigger lead form.
    """
    t = str(text or "").strip()
    if not t:
        return {
            "intent": "none",
            "intents": [],
            "should_offer_lead": False,
            "reason": "empty_message",
        }
    intents: list[str] = []
    for name, pat in _INTENT_PATTERNS:
        if pat.search(t):
            intents.append(name)
    contact = detect_lead_from_text(t)
    if contact.get("phone") or contact.get("email"):
        if "contact_provided" not in intents:
            intents.append("contact_provided")
    primary = intents[0] if intents else "none"
    should_offer = bool(intents)
    reason = "matched:" + ",".join(intents) if intents else "no_clear_lead_intent"
    return {
        "intent": primary,
        "intents": intents,
        "should_offer_lead": should_offer,
        "reason": reason,
        "contact": contact,
    }
