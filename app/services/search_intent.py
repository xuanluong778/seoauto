"""
Search intent classification (informational | navigational | transactional | commercial | local).
"""

from __future__ import annotations

import os
import re
from collections import Counter
from typing import Any

_INFO = re.compile(
    r"\b(how to|what is|what are|why |when |where |guide|tutorial|learn|meaning|definition|tips|ideas)\b",
    re.I,
)
_INFO_VI = re.compile(
    r"\b(cach|cách|huong dan|hướng dẫn|la gi|là gì|tai sao|tại sao|vi sao|vì sao|"
    r"khi nao|khi nào|o dau|ở đâu|lam sao|làm sao|kinh nghiem|kinh nghiệm|meo|mẹo|"
    r"y nghia|ý nghĩa|dinh nghia|định nghĩa|hoc|học)\b",
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
# Hire / service / agency — commercial investigation (NOT informational)
_SERVICE_HIRE_VI = re.compile(
    r"\b(dich vu|dịch vụ|thue|thuê|cho thue|cho thuê|thuê|thuê|agency|"
    r"cong ty|cong ty|công ty|cty|trung tam|trung tâm|don vi|đơn vị cung cap|"
    r"cung cap|dịch vụ seo|dich vu seo|thue seo|thuê seo)\b",
    re.I,
)
_COMM = re.compile(
    r"\b(best|top|review|vs|compare|alternative|software|tool|service|agency|"
    r"for sale)\b",
    re.I,
)
_COMM_VI = re.compile(
    r"\b(tot nhat|tốt nhất|top|review|danh gia|đánh giá|so sanh|so sánh|"
    r"vs|nen mua|nên mua|hang nao|hãng nào|loai nao|loại nào|"
    r"gia re|giá rẻ|uy tin|uy tín)\b",
    re.I,
)
_LOCAL = re.compile(r"\b(near me|nearby|local)\b", re.I)
_LOCAL_VI = re.compile(
    r"\b(gan day|gần đây|gan toi|gần tôi|gan minh|gần mình|tai|tại|o|ở|"
    r"quan|quận|huyen|huyện|phuong|phường|tinh|tỉnh|thanh pho|thành phố|"
    r"tp\.?\s*hcm|ha noi|hà nội|da nang|đà nẵng)\b",
    re.I,
)
_NAV = re.compile(r"\.(com|io|net|org)\b|login|sign in|portal|dashboard", re.I)
_NAV_VI = re.compile(r"\b(dang nhap|đăng nhập|dang ky|đăng ký|trang chu|trang chủ|app)\b", re.I)

INTENT_LABELS = frozenset({"informational", "navigational", "transactional", "commercial", "local", "mixed_intent"})
MONEY_INTENTS = frozenset({"transactional", "commercial", "local"})


def has_informational_pattern(keyword: str) -> bool:
    low = (keyword or "").strip().lower()
    return bool(_INFO.search(low) or _INFO_VI.search(low))


def has_money_intent_pattern(keyword: str) -> bool:
    low = (keyword or "").strip().lower()
    return bool(
        _TRANS.search(low)
        or _TRANS_VI.search(low)
        or _SERVICE_HIRE_VI.search(low)
        or _COMM.search(low)
        or _COMM_VI.search(low)
    )


def normalize_intent_label(intent: str) -> str:
    it = (intent or "informational").strip().lower()
    if it in INTENT_LABELS:
        return it
    if it == "ecommerce":
        return "transactional"
    return "informational"


def classify_search_intent(keyword: str, *, brand_terms: set[str] | None = None) -> dict[str, Any]:
    """
    Returns ``intent`` + ``confidence`` + ``reasoning`` (short strings for explainability).
    """
    k = (keyword or "").strip()
    low = k.lower()
    reasons: list[str] = []
    scores = {
        "informational": 0.0,
        "navigational": 0.0,
        "transactional": 0.0,
        "commercial": 0.0,
        "local": 0.0,
    }

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

    if _LOCAL.search(low) or _LOCAL_VI.search(low):
        scores["local"] += 0.52
        reasons.append("Local / geo modifier in query")

    if _TRANS.search(low) or _TRANS_VI.search(low):
        scores["transactional"] += 0.62
        reasons.append("Transactional lexicon (buy/price/order/...)")

    if _SERVICE_HIRE_VI.search(low):
        scores["commercial"] += 0.58
        reasons.append("Service/hire/agency lexicon (dịch vụ/thuê/...)")
        if _TRANS_VI.search(low):
            scores["transactional"] += 0.35
            reasons.append("Price/quote combined with service query")

    if _SERVICE_VI.search(low) and scores["transactional"] < 0.8:
        scores["transactional"] += 0.38
        reasons.append("Service intent lexicon (repair/install/...)")

    if (_COMM.search(low) or _COMM_VI.search(low)) and scores["transactional"] < 0.55:
        scores["commercial"] += 0.5
        reasons.append("Commercial investigation lexicon (best/review/vs/...)")

    if _INFO.search(low) or _INFO_VI.search(low):
        scores["informational"] += 0.55
        reasons.append("Informational question/guide pattern")

    # Money patterns suppress weak informational prior
    if has_money_intent_pattern(k) and not has_informational_pattern(k):
        scores["informational"] = max(0.0, scores["informational"] - 0.35)

    if len(low.split()) <= 2 and low[0:1].isupper() if low else False:
        scores["navigational"] += 0.2
        reasons.append("Short proper-like phrase — possible brand navigational")

    if sum(scores.values()) < 0.15:
        if has_money_intent_pattern(k):
            scores["commercial"] = 0.42
            reasons.append("Soft commercial prior for service-like phrase")
        else:
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

    Strict: informational vs commercial/transactional/local → 0.0 (must use SERP override to merge).
    """
    a = normalize_intent_label(intent_a)
    b = normalize_intent_label(intent_b)
    if a == b:
        return 1.0
    if a == "mixed_intent" and b == "mixed_intent":
        return 0.58
    if a == "mixed_intent" or b == "mixed_intent":
        other = b if a == "mixed_intent" else a
        if other in ("informational", "commercial"):
            return 0.18
        if other == "transactional":
            return 0.12
        if other == "local":
            return 0.15
        if other == "navigational":
            return 0.1
        return 0.12
    pair = {a, b}
    if pair == {"informational", "commercial"}:
        return 0.0
    if pair == {"informational", "transactional"}:
        return 0.0
    if pair == {"informational", "local"}:
        return 0.0
    if pair == {"commercial", "transactional"}:
        return 0.35
    if pair == {"commercial", "local"}:
        return 0.4
    if pair == {"transactional", "local"}:
        return 0.38
    return 0.0


def serp_shared_url_merge_count() -> int:
    """Shared normalized URLs in top-10 SERP required to merge (SERP-primary clustering)."""
    return max(1, min(10, int(os.getenv("KEYWORD_CLUSTER_SERP_MIN_SHARED_URLS", "3"))))


def intent_merge_allowed(intent_a: str, intent_b: str, *, serp_jaccard: float = 0.0) -> bool:
    """
    Gate for semantic fallback only. SERP-primary clustering uses shared URL count (>=3)
    and does not block merge on intent when enough URLs overlap.
    """
    a = normalize_intent_label(intent_a)
    b = normalize_intent_label(intent_b)
    if a == b:
        return True
    serp = max(0.0, min(1.0, float(serp_jaccard or 0.0)))
    base_min = float(os.getenv("KEYWORD_CLUSTER_CROSS_INTENT_MIN_SERP", "0.78"))
    info_money = {"informational"} & {a, b} and MONEY_INTENTS & {a, b}
    if info_money:
        return serp >= float(os.getenv("KEYWORD_CLUSTER_INFO_MONEY_MIN_SERP", "0.85"))
    if {"navigational"} & {a, b} and a != b:
        return serp >= max(base_min, 0.82)
    return serp >= base_min


def effective_intent_for_clustering(row: dict[str, Any]) -> str:
    """
    Single intent label used for union-find blocking (lexical rules beat weak SERP defaults).
    """
    kw = str(row.get("keyword") or "").strip()
    rule_int = normalize_intent_label(str(row.get("intent") or "informational"))
    rule_conf = float(row.get("intent_confidence") or 0.5)
    serp_int = normalize_intent_label(str(row.get("intent_cluster") or ""))

    if not kw:
        return "informational"

    fresh = classify_search_intent(kw)
    fresh_int = normalize_intent_label(str(fresh.get("intent") or "informational"))
    fresh_conf = float(fresh.get("confidence") or 0.5)

    if fresh_int in MONEY_INTENTS and fresh_conf >= 0.48:
        return fresh_int
    if fresh_int == "navigational" and fresh_conf >= 0.5:
        return fresh_int
    if has_informational_pattern(kw) and fresh_int == "informational":
        return "informational"
    if rule_int in MONEY_INTENTS and rule_conf >= 0.48:
        return rule_int
    if has_informational_pattern(kw) and rule_int == "informational":
        return "informational"
    if serp_int and serp_int != "informational" and not has_informational_pattern(kw):
        if intent_similarity(rule_int, serp_int) >= 0.35 or rule_conf < 0.55:
            return serp_int
    if fresh_conf >= rule_conf:
        return fresh_int
    return rule_int


def compute_cluster_intent_purity(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Intent purity + conflict flag for a cluster."""
    if not rows:
        return {
            "purity": 1.0,
            "dominant_intent": "informational",
            "has_conflict": False,
            "intent_conflict": False,
            "distribution": {},
        }
    labels = [effective_intent_for_clustering(r) for r in rows if isinstance(r, dict)]
    if not labels:
        return {
            "purity": 1.0,
            "dominant_intent": "informational",
            "has_conflict": False,
            "intent_conflict": False,
            "distribution": {},
        }
    ct = Counter(labels)
    dom, cnt = ct.most_common(1)[0]
    purity = cnt / len(labels)
    min_purity = float(os.getenv("CLUSTER_INTENT_PURITY_MIN", "0.85"))
    mixed = len(ct) > 1
    conflict = mixed and purity < min_purity
    return {
        "purity": round(purity, 4),
        "dominant_intent": dom,
        "has_conflict": mixed,
        "intent_conflict": conflict,
        "distribution": {k: round(v / len(labels), 3) for k, v in ct.items()},
    }


def aggregate_cluster_intent(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Vote by confidence-weighted intent from per-keyword rows."""
    agg: dict[str, float] = {
        "informational": 0.0,
        "navigational": 0.0,
        "transactional": 0.0,
        "commercial": 0.0,
        "local": 0.0,
        "mixed_intent": 0.0,
    }
    layout_dists: list[dict[str, float]] = []
    for r in rows:
        it = normalize_intent_label(
            str(effective_intent_for_clustering(r) if isinstance(r, dict) else "informational")
        )
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
        keys5 = ["informational", "navigational", "transactional", "commercial", "local"]
        blend = {k: round(sum(d.get(k, 0) for d in layout_dists) / len(layout_dists), 4) for k in keys5}
        out["serp_intent_distribution_avg"] = blend
    return out
