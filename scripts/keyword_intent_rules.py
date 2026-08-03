"""
Rule-based keyword intent: informational, commercial, navigational, mixed.
"""

from __future__ import annotations

import re

_NAV = re.compile(
    r"\b(login|sign\s*in|signin|register|signup|official|homepage|www\.|\.com|"
    r"facebook|youtube|instagram|twitter|linkedin|maps?|đăng\s*nhập|trang\s*chủ)\b",
    re.I,
)
_COMM = re.compile(
    r"\b(buy|price|cheap|deal|discount|coupon|order|shipping|subscribe|hire|agency|"
    r"quote|software|tool|app|download|demo|trial|vs\b|review|best\b|near\s*me|"
    r"giá|mua|bán|thuê|dịch\s*vụ|khuyến\s*mại)\b",
    re.I,
)
_INFO = re.compile(
    r"\b(how\b|what\b|why\b|when\b|where\b|guide|tutorial|meaning|definition|"
    r"learn|course|example|ideas?|tips?|là\s*gì|cách|hướng\s*dẫn|ý\s*nghĩa)\b",
    re.I,
)


def classify_intent_rules(keyword: str) -> str:
    """
    Returns one of: informational, commercial, navigational, mixed.
    """
    s = (keyword or "").strip()
    if not s:
        return "informational"
    low = s.lower()
    has_nav = bool(_NAV.search(low))
    has_comm = bool(_COMM.search(low))
    has_info = bool(_INFO.search(low))
    if has_nav and not has_comm and not has_info:
        return "navigational"
    if has_nav and (has_comm or has_info):
        return "mixed"
    if has_comm and has_info:
        return "mixed"
    if has_comm:
        return "commercial"
    if has_info:
        return "informational"
    if re.search(r"\b(inc|ltd|llc|corp|brand|®|™)\b", low):
        return "navigational"
    return "informational"


def majority_intent(intents: list[str]) -> str:
    if not intents:
        return "informational"
    order = ("mixed", "commercial", "navigational", "informational")
    counts: dict[str, int] = {}
    for i in intents:
        counts[i] = counts.get(i, 0) + 1
    best = max(counts.values())
    candidates = [k for k, v in counts.items() if v == best]
    for o in order:
        if o in candidates:
            return o
    return candidates[0]
