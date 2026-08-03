"""Chatbot CSKH — lead extraction + clear lead-intent detection."""

from __future__ import annotations

import re
from typing import Any

_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?84|0)(?:3|5|7|8|9)\d{8}(?!\d)",
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
        r"liên\s*hệ\s*(ở\s*đâu|như\s*thế\s*nào|qua)|phone|address)\b",
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
    return digits[:32] if len(digits) >= 9 else ""


def extract_phone(text: str) -> str:
    for m in _PHONE_RE.finditer(str(text or "")):
        phone = _normalize_phone(m.group(0))
        if len(phone) >= 10:
            return phone
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
    if len(t) >= 15 and not extract_phone(t):
        return t[:2000]
    return ""


def detect_lead_from_text(text: str) -> dict[str, Any]:
    phone = extract_phone(text)
    name = extract_name(text)
    need = extract_need(text) if phone or name else ""
    return {
        "phone": phone,
        "name": name,
        "need": need,
        "has_lead_signal": bool(phone or (name and need)),
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
    primary = intents[0] if intents else "none"
    return {
        "intent": primary,
        "intents": intents,
        "should_offer_lead": bool(intents),
        "reason": "matched:" + ",".join(intents) if intents else "no_clear_lead_intent",
    }
