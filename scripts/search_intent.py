"""
Search intent classification (informational | navigational | transactional | commercial).
"""

from __future__ import annotations

import re
from typing import Any

_INFO = re.compile(
    r"\b(how to|what is|what are|why |when |where |guide|tutorial|learn|meaning|definition|tips|ideas)\b",
    re.I,
)
_INFO_VI = re.compile(
    r"\b(cach|cách|huong dan|hướng dẫn|la gi|là gì|tai sao|tại sao|vi sao|vì sao|"
    r"khi nao|khi nào|o dau|ở đâu|lam sao|làm sao|kinh nghiem|kinh nghiệm|meo|mẹo|"
    r"y nghia|ý nghĩa|dinh nghia|định nghĩa)\b",
    re.I,
)
_TRANS = re.compile(
    r"\b(buy|order|purchase|price|pricing|cheap|deal|discount|coupon|subscribe|"
    r"book now|get quote|checkout|cart|pay|download|free trial)\b",
    re.I,
)
_TRANS_VI = re.compile(
    r"\b(mua|dat mua|đặt mua|dat hang|đặt hàng|order|gia|giá|bao nhieu|bao nhiêu|"
    r"bang gia|bảng giá|bao gia|báo giá|khuyen mai|khuyến mãi|giam gia|giảm giá|"
    r"ship|van chuyen|vận chuyển|thanh toan|thanh toán|tra gop|trả góp|"
    r"dat lich|đặt lịch|lien he|liên hệ|goi|gọi)\b",
    re.I,
)
_SERVICE_VI = re.compile(
    r"\b(sua|sửa|chua|chữa|thay|thay pin|thay man|thay màn|"
    r"bao hanh|bảo hành|bao tri|bảo trì|cai dat|cài đặt|lap dat|lắp đặt)\b",
    re.I,
)
_COMM = re.compile(
    r"\b(best|top|review|vs|compare|alternative|software|tool|service|agency|"
    r"near me|for sale)\b",
    re.I,
)
_COMM_VI = re.compile(
    r"\b(tot nhat|tốt nhất|top|review|danh gia|đánh giá|so sanh|so sánh|"
    r"vs|nen mua|nên mua|hang nao|hãng nào|loai nao|loại nào|"
    r"gia re|giá rẻ|uy tin|uy tín)\b",
    re.I,
)
# crude brand/navigational: single token proper-like or contains .com / login
_NAV = re.compile(r"\.(com|io|net|org)\b|login|sign in|portal|dashboard", re.I)
_NAV_VI = re.compile(r"\b(dang nhap|đăng nhập|dang ky|đăng ký|trang chu|trang chủ|app)\b", re.I)


def classify_search_intent(keyword: str, *, brand_terms: set[str] | None = None) -> dict[str, Any]:
    """
    Returns ``intent`` + ``confidence`` + ``reasoning`` (short strings for explainability).
    """
    k = (keyword or "").strip()
    low = k.lower()
    reasons: list[str] = []
    scores = {"informational": 0.0, "navigational": 0.0, "transactional": 0.0, "commercial": 0.0}

    if _NAV.search(low):
        scores["navigational"] += 0.55
        reasons.append("URL/login/nav pattern in query")
    if _NAV_VI.search(low):
        scores["navigational"] += 0.35
        reasons.append("Vietnamese navigational pattern")

    if brand_terms:
        for b in brand_terms:
            if b and len(b) > 2 and b.lower() in low:
                scores["navigational"] += 0.45
                reasons.append(f"Contains brand token «{b}»")
                break

    if _TRANS.search(low) or _TRANS_VI.search(low):
        scores["transactional"] += 0.62
        reasons.append("Transactional lexicon (buy/price/order/...)")
    # Service queries in Vietnamese are usually transactional (hire/repair/install).
    if _SERVICE_VI.search(low) and scores["transactional"] < 0.8:
        scores["transactional"] += 0.38
        reasons.append("Service intent lexicon (repair/install/...)")

    if (_COMM.search(low) or _COMM_VI.search(low)) and scores["transactional"] < 0.55:
        scores["commercial"] += 0.5
        reasons.append("Commercial investigation lexicon (best/review/vs/...)")

    if _INFO.search(low) or _INFO_VI.search(low):
        scores["informational"] += 0.55
        reasons.append("Informational question/guide pattern")

    if len(low.split()) <= 2 and low[0:1].isupper() if low else False:
        scores["navigational"] += 0.2
        reasons.append("Short proper-like phrase — possible brand navigational")

    # default bias
    if sum(scores.values()) < 0.15:
        scores["informational"] = 0.45
        reasons.append("Default soft-informational prior for ambiguous phrase")

    intent = max(scores, key=lambda x: scores[x])
    raw = scores[intent]
    conf = min(0.92, 0.35 + raw)
    return {
        "intent": intent,
        "confidence": round(conf, 3),
        "reasoning": reasons[:6] or ["Heuristic lexicon + phrase shape"],
        "scores": {k: round(v, 3) for k, v in scores.items()},
    }


def intent_similarity(intent_a: str, intent_b: str) -> float:
    """
    Pairwise intent alignment for hybrid clustering.

    * same label → 1.0
    * informational + commercial (research / evaluation) → 0.5
    * ``mixed_intent`` vs pure labels → thấp (tránh gom nhầm SERP đa dạng)
    * ``mixed_intent`` + ``mixed_intent`` → trung bình (cùng “không đồng nhất”)
    * otherwise → 0.0 (strict: navigational vs transactional, etc.)
    """
    a = (intent_a or "informational").strip().lower()
    b = (intent_b or "informational").strip().lower()
    if a == b:
        return 1.0
    if a == "mixed_intent" and b == "mixed_intent":
        return 0.58
    if a == "mixed_intent" or b == "mixed_intent":
        other = b if a == "mixed_intent" else a
        if other in ("informational", "commercial"):
            return 0.22
        if other == "transactional":
            return 0.12
        if other == "navigational":
            return 0.1
        return 0.12
    pair = {a, b}
    if pair == {"informational", "commercial"}:
        return 0.5
    return 0.0


def aggregate_cluster_intent(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Vote by confidence-weighted intent from per-keyword rows (ưu tiên ``intent_cluster`` từ SERP layout)."""
    agg: dict[str, float] = {
        "informational": 0.0,
        "navigational": 0.0,
        "transactional": 0.0,
        "commercial": 0.0,
        "mixed_intent": 0.0,
    }
    layout_dists: list[dict[str, float]] = []
    for r in rows:
        it = str(r.get("intent_cluster") or r.get("intent") or "informational")
        c = float(r.get("intent_confidence") or 0.5)
        if it in agg:
            agg[it] += c
        sig = r.get("serp_layout_intent")
        if isinstance(sig, dict):
            d = sig.get("intent_distribution")
            if isinstance(d, dict):
                layout_dists.append({k: float(d.get(k) or 0) for k in agg if k != "mixed_intent"})
    dom = max(agg, key=lambda x: agg[x])
    tot = sum(agg.values()) or 1.0
    out: dict[str, Any] = {
        "intent": dom,
        "confidence": round(min(0.95, agg[dom] / tot + 0.15), 3),
        "distribution": {k: round(v / tot, 3) for k, v in agg.items()},
    }
    if layout_dists:
        keys4 = ["informational", "navigational", "transactional", "commercial"]
        blend = {k: round(sum(d.get(k, 0) for d in layout_dists) / len(layout_dists), 4) for k in keys4}
        out["serp_intent_distribution_avg"] = blend
    return out
