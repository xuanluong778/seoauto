"""
Rule-based keyword intent for research: informational, commercial, transactional,
education, local, navigational, mixed, unknown.
"""

from __future__ import annotations

import re
from typing import Any

_NAV = re.compile(
    r"\b(login|sign\s*in|signin|register|signup|official|homepage|www\.|"
    r"facebook|youtube|instagram|twitter|linkedin|maps?|đăng\s*nhập|trang\s*chủ)\b",
    re.I,
)
_LOCAL = re.compile(
    r"\b(tphcm|tp\.?\s*hcm|tp\s*hồ\s*chí\s*minh|hà\s*nội|ha\s*noi|hanoi|đà\s*nẵng|da\s*nang|"
    r"quận\s*\d+|quan\s*\d+|huyện|tỉnh|thành\s*phố|thanh\s*pho|gần\s*đây|gan\s*day|near\s*me)\b",
    re.I,
)
_SERVICE_VI = re.compile(
    r"\b(sửa|sua\b|dịch\s*vụ|dich\s*vu|tại\s*nhà|tai\s*nha|tận\s*nơi|tan\s*noi|"
    r"gần\s*đây|gan\s*day|giá\b|gia\b|báo\s*giá|bao\s*gia|quận|quan\b|tphcm|thợ|tho\b)\b",
    re.I,
)
_EDU = re.compile(
    r"\b(khóa\s*học|khoa\s*hoc|đào\s*tạo|dao\s*tao|trung\s*tâm|trung\s*tam|"
    r"lớp\s*học|lop\s*hoc|học\s*viện|hoc\s*vien|training|khoá\s*học)\b",
    re.I,
)
_TRANS = re.compile(
    r"\b(giá|gia\b|báo\s*giá|bao\s*gia|mua\b|thuê|thue\b|phần\s*mềm|phan\s*mem|"
    r"tool\b|software|app\b|download|tải\s*về|tai\s*ve|đặt\s*mua|dat\s*mua)\b",
    re.I,
)
_COMM = re.compile(
    r"\b(dịch\s*vụ|dich\s*vu|công\s*ty|cong\s*ty|agency|top\b|review|đánh\s*giá|danh\s*gia|"
    r"so\s*sánh|best\b|vs\b|tư\s*vấn|tu\s*van)\b",
    re.I,
)
_INFO = re.compile(
    r"\b(how\b|what\b|why\b|when\b|where\b|guide|tutorial|meaning|definition|"
    r"learn|example|ideas?|tips?|là\s*gì|la\s*gi|cách|huong\s*dan|hướng\s*dẫn|ý\s*nghĩa)\b",
    re.I,
)

_INTENT_ORDER = ("mixed", "local", "education", "transactional", "commercial", "navigational", "informational", "unknown")


def classify_intent_rules(keyword: str) -> str:
    """Returns intent label string (backward compatible)."""
    return str(classify_intent_detail(keyword).get("intent") or "unknown")


def classify_intent_detail(keyword: str) -> dict[str, Any]:
    """
    Rule-based intent with confidence.
    No match → unknown (not informational).
    """
    s = (keyword or "").strip()
    if not s:
        return {"intent": "unknown", "confidence": 0.0, "source": "N/A"}

    low = s.lower()
    flags = {
        "navigational": bool(_NAV.search(low)),
        "local": bool(_LOCAL.search(low)),
        "education": bool(_EDU.search(low)),
        "transactional": bool(_TRANS.search(low)),
        "commercial": bool(_COMM.search(low) or _SERVICE_VI.search(low)),
        "informational": bool(_INFO.search(low)),
    }

    active = [k for k, v in flags.items() if v]
    if not active:
        if re.search(r"\b(inc|ltd|llc|corp|brand|®|™)\b", low):
            return {"intent": "navigational", "confidence": 0.55, "source": "rules"}
        if _SERVICE_VI.search(low):
            if _LOCAL.search(low):
                return {"intent": "local", "confidence": 0.8, "source": "rules"}
            return {"intent": "commercial", "confidence": 0.78, "source": "rules"}
        return {"intent": "unknown", "confidence": 0.0, "source": "N/A"}

    if flags["navigational"] and len(active) == 1:
        return {"intent": "navigational", "confidence": 0.9, "source": "rules"}
    if flags["transactional"] and set(active) <= {"transactional", "commercial"}:
        return {"intent": "transactional", "confidence": 0.88, "source": "rules"}
    if len(active) >= 2:
        if flags["education"] and not flags["transactional"] and not flags["local"]:
            return {"intent": "education", "confidence": 0.86, "source": "rules"}
        if flags["local"] and flags["commercial"] and not flags["transactional"]:
            return {"intent": "local", "confidence": 0.84, "source": "rules"}
        primary = _pick_primary_intent(flags)
        return {"intent": "mixed", "confidence": 0.75, "source": "rules", "mixed_signals": active, "primary": primary}

    intent = active[0]
    conf = 0.88 if intent in ("education", "transactional", "informational", "local") else 0.82
    return {"intent": intent, "confidence": conf, "source": "rules"}


def _pick_primary_intent(flags: dict[str, bool]) -> str:
    for name in ("local", "education", "transactional", "commercial", "informational", "navigational"):
        if flags.get(name):
            return name
    return "unknown"


def majority_intent(intents: list[str]) -> str:
    if not intents:
        return "unknown"
    counts: dict[str, int] = {}
    for i in intents:
        k = (i or "unknown").strip().lower() or "unknown"
        counts[k] = counts.get(k, 0) + 1
    best = max(counts.values())
    candidates = [k for k, v in counts.items() if v == best]
    for o in _INTENT_ORDER:
        if o in candidates:
            return o
    return candidates[0]
