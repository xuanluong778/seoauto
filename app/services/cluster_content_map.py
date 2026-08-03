"""
Enrich keyword cluster output for SaaS Content Map → Content AI flow.
Does not change clustering engine — post-processes raw cluster dicts only.
"""

from __future__ import annotations

import os
import re
from typing import Any

from app.services.cluster_planning_output import suggested_content_type
from app.services.search_intent import effective_intent_for_clustering, normalize_intent_label

_REAL_VOLUME_SOURCES = frozenset({"api", "dataforseo", "api_cache", "google_ads"})
_FAQ_RE = re.compile(
    r"(\?|^(là gì|là ai|là sao|bao nhiêu|ở đâu|khi nào|tại sao|how to|what is|why |when |where ))",
    re.I,
)


def _is_real_volume(row: dict[str, Any]) -> bool:
    src = str(row.get("volume_source") or "").lower()
    return src in _REAL_VOLUME_SOURCES


def _volume_value(row: dict[str, Any]) -> int | None:
    if not _is_real_volume(row):
        return None
    sv = row.get("search_volume")
    if isinstance(sv, dict):
        try:
            v = int(sv.get("avg_monthly") or 0)
        except (TypeError, ValueError):
            return None
    else:
        try:
            v = int(sv or 0)
        except (TypeError, ValueError):
            return None
    return v if v > 0 else None


def _cpc_value(row: dict[str, Any]) -> float | None:
    for key in ("cpc_avg", "cpc"):
        if row.get(key) is not None:
            try:
                v = float(row[key])
                return v if v >= 0 else None
            except (TypeError, ValueError):
                pass
    return None


def _competition_value(row: dict[str, Any]) -> str | None:
    for key in ("competition", "competition_index", "competition_level"):
        val = row.get(key)
        if val is None or val == "":
            continue
        if isinstance(val, (int, float)):
            return str(val)
        s = str(val).strip()
        if s:
            return s
    return None


def _token_overlap(a: str, b: str) -> float:
    ta = {t for t in re.split(r"\W+", (a or "").lower()) if len(t) > 1}
    tb = {t for t in re.split(r"\W+", (b or "").lower()) if len(t) > 1}
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return round(inter / union, 4) if union else 0.0


def _assign_content_role(
    *,
    keyword: str,
    main_kw: str,
    rank: int,
    cluster_size: int,
) -> str:
    low = keyword.lower().strip()
    main_low = main_kw.lower().strip()
    if low == main_low or rank == 0:
        return "primary"
    if _FAQ_RE.search(keyword):
        return "faq"
    if rank <= 2 and cluster_size > 3:
        return "secondary"
    overlap = _token_overlap(keyword, main_kw)
    if overlap >= 0.45 and rank > 0:
        return "semantic"
    if rank <= max(4, cluster_size // 3):
        return "secondary"
    return "supporting"


def _matching_point(
    *,
    row: dict[str, Any],
    main_kw: str,
    cluster_intent: str,
    rank: int,
    cluster_size: int,
    serp_overlap: float | None,
) -> int:
    score = 40.0
    kw_intent = str(row.get("intent_cluster") or row.get("intent") or "").lower()
    if kw_intent and kw_intent == (cluster_intent or "").lower():
        score += 20.0
    elif kw_intent:
        score += 8.0
    vol = _volume_value(row)
    if vol and vol > 0:
        score += min(18.0, 18.0 * (1.0 - rank / max(1, cluster_size)))
    if serp_overlap is not None:
        score += min(22.0, serp_overlap * 22.0)
    score += _token_overlap(str(row.get("keyword") or ""), main_kw) * 15.0
    return int(max(0, min(100, round(score))))


def _pair_serp_map(explain: dict[str, Any] | None, ordered_kws: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    if not explain or not ordered_kws:
        return out
    main = ordered_kws[0]
    for item in explain.get("strong_pairs") or []:
        if not isinstance(item, dict):
            continue
        pair = str(item.get("pair") or "")
        sim = item.get("serp_jaccard")
        if "|" not in pair or sim is None:
            continue
        a, _, b = [x.strip() for x in pair.partition("|")]
        try:
            v = float(sim)
        except (TypeError, ValueError):
            continue
        if a == main and b:
            out[b.lower()] = v
        elif b == main and a:
            out[a.lower()] = v
    return out


def _content_angle(intent: str, content_type: str) -> str:
    it = (intent or "informational").lower()
    ct = (content_type or "").lower()
    if "faq" in ct or it == "informational":
        return "Giải đáp & hướng dẫn chi tiết"
    if it == "commercial" or "comparison" in ct:
        return "So sánh & đánh giá giúp ra quyết định"
    if it == "transactional":
        return "Tập trung chuyển đổi & CTA rõ ràng"
    if it == "navigational":
        return "Định vị thương hiệu & tài nguyên"
    if it == "local":
        return "Landing địa phương & dịch vụ gần bạn"
    if "pillar" in ct or "hub" in ct:
        return "Trụ cột chủ đề — bao quát toàn cụm"
    return "Bài chuyên sâu theo chủ đề cụm"


def _content_priority(total_volume: int | None, confidence: float, keyword_count: int) -> str:
    vol_score = 0.0
    if total_volume and total_volume > 0:
        if total_volume >= 5000:
            vol_score = 1.0
        elif total_volume >= 1000:
            vol_score = 0.75
        elif total_volume >= 200:
            vol_score = 0.5
        else:
            vol_score = 0.25
    composite = confidence * 0.55 + vol_score * 0.35 + min(1.0, keyword_count / 8.0) * 0.10
    if composite >= 0.72:
        return "high"
    if composite >= 0.48:
        return "medium"
    return "low"


def compute_priority_score(
    *,
    total_volume: int | None,
    intent: str,
    confidence_score: float,
    keyword_count: int,
) -> float:
    """0–100: volume + commercial intent + confidence + cluster size."""
    vol_score = 0.0
    if total_volume and total_volume > 0:
        if total_volume >= 10000:
            vol_score = 1.0
        elif total_volume >= 3000:
            vol_score = 0.85
        elif total_volume >= 1000:
            vol_score = 0.7
        elif total_volume >= 300:
            vol_score = 0.5
        else:
            vol_score = 0.3
    it = (intent or "informational").lower()
    intent_score = {
        "transactional": 1.0,
        "commercial": 0.9,
        "mixed_intent": 0.55,
        "informational": 0.45,
        "navigational": 0.35,
        "ecommerce": 0.88,
    }.get(it, 0.4)
    conf = confidence_score / 100.0 if confidence_score > 1 else max(0.0, min(1.0, confidence_score))
    kw_score = min(1.0, keyword_count / 10.0)
    raw = vol_score * 0.35 + intent_score * 0.25 + conf * 0.25 + kw_score * 0.15
    return round(raw * 100.0, 1)


def _keywords_by_role(items: list[dict[str, Any]], role: str, *, cluster_intent: str = "") -> list[str]:
    ci = normalize_intent_label(cluster_intent)
    out: list[str] = []
    for it in items:
        if it.get("content_role") != role or not it.get("keyword"):
            continue
        if ci:
            kw_int = normalize_intent_label(str(it.get("intent") or ""))
            if kw_int and kw_int != ci:
                continue
        out.append(str(it.get("keyword") or "").strip())
    return out


def _target_word_count(intent: str, ctype: str, keyword_count: int, faq_count: int) -> int:
    it = (intent or "informational").lower()
    ct = (ctype or "").lower()
    base = 1600
    if it in ("transactional", "ecommerce") or "landing" in ct or "conversion" in ct:
        base = 1200
    elif it == "commercial" or "comparison" in ct:
        base = 1500
    elif "long_form" in ct or "guide" in ct or "pillar" in ct:
        base = 2200
    elif it == "informational":
        base = 1800
    base += min(600, max(0, keyword_count - 3) * 80)
    base += min(400, faq_count * 100)
    return int(max(800, min(4500, base)))


def _recommended_title(main_kw: str, intent: str, ctype: str) -> str:
    kw = (main_kw or "").strip()
    if not kw:
        return ""
    it = (intent or "informational").lower()
    ct = (ctype or "").lower()
    if it == "transactional" or "landing" in ct:
        return f"{kw} — Giải pháp & báo giá"
    if it == "commercial" or "comparison" in ct:
        return f"{kw}: So sánh & lựa chọn tốt nhất"
    if "faq" in ct or kw.endswith("?"):
        return f"{kw} — Giải đáp chi tiết"
    return f"{kw}: Hướng dẫn chi tiết & thực hành"


def _meta_description(main_kw: str, angle: str, secondary: list[str]) -> str:
    kw = (main_kw or "").strip()
    hook = (angle or "Hướng dẫn chi tiết").strip().rstrip(".")
    extra = ""
    if secondary:
        extra = f" Bao gồm: {', '.join(secondary[:3])}."
    text = f"{hook} cho từ khóa «{kw}».{extra}"
    if len(text) > 158:
        text = text[:155].rstrip() + "…"
    return text


def build_content_plan(
    *,
    cluster_id: str,
    topic: str,
    main_kw: str,
    keyword_items: list[dict[str, Any]],
    cluster_intent: str,
    suggested_content_type: str,
    content_angle: str,
    total_volume: int | None,
    confidence_score: float,
) -> dict[str, Any]:
    secondary = _keywords_by_role(keyword_items, "secondary", cluster_intent=cluster_intent)
    semantic = _keywords_by_role(keyword_items, "semantic", cluster_intent=cluster_intent)
    faq = _keywords_by_role(keyword_items, "faq", cluster_intent=cluster_intent)
    supporting = _keywords_by_role(keyword_items, "supporting", cluster_intent=cluster_intent)
    if not secondary:
        secondary = supporting[:4]
    outline = _outline_hint(main_kw, keyword_items, cluster_intent, suggested_content_type)
    kw_count = len(keyword_items)
    priority = compute_priority_score(
        total_volume=total_volume,
        intent=cluster_intent,
        confidence_score=confidence_score,
        keyword_count=kw_count,
    )
    title = _recommended_title(main_kw, cluster_intent, suggested_content_type)
    meta = _meta_description(main_kw, content_angle, secondary + semantic)
    twc = _target_word_count(cluster_intent, suggested_content_type, kw_count, len(faq))
    return {
        "plan_id": f"plan_{cluster_id}",
        "cluster_id": cluster_id,
        "topic": topic,
        "primary_keyword": main_kw,
        "secondary_keywords": secondary,
        "semantic_keywords": semantic,
        "faq_keywords": faq,
        "intent": cluster_intent,
        "suggested_content_type": suggested_content_type,
        "content_angle": content_angle,
        "priority_score": priority,
        "target_word_count": twc,
        "recommended_title": title,
        "meta_description": meta,
        "outline": outline,
    }


def build_content_plans_from_clusters(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    for c in clusters:
        plan = c.get("content_plan")
        if isinstance(plan, dict) and plan.get("primary_keyword"):
            plans.append(plan)
    return plans


def compute_confidence_score(
    *,
    serp_overlap: float,
    intent_confidence: float,
    semantic_score: float | None,
    volume_coverage: float,
    dedupe_ratio: float,
    cluster_strictness: str | None = None,
    weak_serp_ratio: float = 0.0,
) -> float:
    sem = semantic_score if semantic_score is not None else serp_overlap * 0.85
    raw = (
        max(0.0, min(1.0, serp_overlap)) * 0.35
        + max(0.0, min(1.0, intent_confidence)) * 0.25
        + max(0.0, min(1.0, sem)) * 0.15
        + max(0.0, min(1.0, volume_coverage)) * 0.15
        + max(0.0, min(1.0, dedupe_ratio)) * 0.10
    )
    strict = (cluster_strictness or "normal").lower().strip()
    if strict == "loose" and weak_serp_ratio > 0.2:
        raw *= max(0.55, 1.0 - weak_serp_ratio * 0.35)
    elif strict == "strict" and serp_overlap < 0.35:
        raw *= 0.88
    return round(raw * 100.0, 1)


def build_keyword_item(
    row: dict[str, Any],
    *,
    main_kw: str,
    cluster_intent: str,
    rank: int,
    cluster_size: int,
    serp_pair_map: dict[str, float],
    cluster_serp_avg: float,
) -> dict[str, Any]:
    kw = str(row.get("keyword") or "").strip()
    low = kw.lower()
    if low == main_kw.lower():
        serp_ov = 1.0
    elif low in serp_pair_map:
        serp_ov = serp_pair_map[low]
    elif cluster_serp_avg > 0:
        serp_ov = cluster_serp_avg
    else:
        serp_ov = None
    role = _assign_content_role(keyword=kw, main_kw=main_kw, rank=rank, cluster_size=cluster_size)
    mp = _matching_point(
        row=row,
        main_kw=main_kw,
        cluster_intent=cluster_intent,
        rank=rank,
        cluster_size=cluster_size,
        serp_overlap=serp_ov,
    )
    return {
        "keyword": kw,
        "volume": _volume_value(row),
        "cpc": _cpc_value(row),
        "competition": _competition_value(row),
        "intent": str(effective_intent_for_clustering(row) if isinstance(row, dict) else cluster_intent or "informational"),
        "matching_point": mp,
        "serp_overlap": round(serp_ov, 4) if serp_ov is not None else None,
        "content_role": role,
    }


def enrich_cluster_for_content_map(
    raw: dict[str, Any],
    *,
    idx: int,
    input_keyword_count: int = 0,
) -> dict[str, Any]:
    """Transform raw clusterer output into SaaS Content Map entity (backward-compatible)."""
    mem_rows = [r for r in (raw.get("keywords") or []) if isinstance(r, dict)]
    main_kw = str(raw.get("main_keyword") or raw.get("cluster_name") or "").strip()
    if not main_kw and mem_rows:
        main_kw = str(mem_rows[0].get("keyword") or "").strip()
    topic = str(raw.get("cluster_name") or main_kw or f"Cụm {idx + 1}").strip()
    cluster_intent = normalize_intent_label(str(raw.get("intent") or "informational"))
    intent_purity = raw.get("intent_purity")
    intent_conflict = bool(raw.get("intent_conflict"))
    explain = raw.get("explain") if isinstance(raw.get("explain"), dict) else {}
    gate_meta = explain.get("intent_gate_meta") if isinstance(explain.get("intent_gate_meta"), dict) else {}
    strictness = str(explain.get("cluster_strictness") or os.getenv("KEYWORD_CLUSTER_STRICTNESS", "normal"))
    weak_pairs = int(gate_meta.get("weak_serp_pairs") or 0)
    pairs_kept = int(gate_meta.get("pairs_kept") or 0)
    weak_serp_ratio = (weak_pairs / pairs_kept) if pairs_kept > 0 else 0.0

    serp_avg = float(raw.get("serp_similarity_avg") or raw.get("serp_overlap_score") or raw.get("cohesion_score") or 0.0)
    intent_conf = float(raw.get("intent_confidence") or 0.65)
    sem_avg = raw.get("semantic_score_avg")
    sem_f = float(sem_avg) if sem_avg is not None else None

    ordered_kws = [str(r.get("keyword") or "").strip() for r in mem_rows if r.get("keyword")]
    serp_pair_map = _pair_serp_map(explain, [main_kw] + [k for k in ordered_kws if k.lower() != main_kw.lower()])

    keyword_items: list[dict[str, Any]] = []
    for rank, row in enumerate(mem_rows):
        keyword_items.append(
            build_keyword_item(
                row,
                main_kw=main_kw,
                cluster_intent=cluster_intent,
                rank=rank,
                cluster_size=len(mem_rows),
                serp_pair_map=serp_pair_map,
                cluster_serp_avg=serp_avg,
            )
        )

    real_vols = [it["volume"] for it in keyword_items if it.get("volume") is not None]
    total_volume: int | None = int(sum(real_vols)) if real_vols else None
    volume_coverage = len(real_vols) / max(1, len(keyword_items))
    dedupe_ratio = len(keyword_items) / max(1, input_keyword_count) if input_keyword_count else 1.0

    confidence = compute_confidence_score(
        serp_overlap=serp_avg,
        intent_confidence=intent_conf,
        semantic_score=sem_f,
        volume_coverage=volume_coverage,
        dedupe_ratio=min(1.0, dedupe_ratio),
        cluster_strictness=strictness,
        weak_serp_ratio=weak_serp_ratio,
    )

    ctype = str(
        raw.get("suggested_content_type")
        or raw.get("recommended_content_type")
        or suggested_content_type(
            cluster_intent=cluster_intent,
            primary_serp_page_type=raw.get("primary_serp_page_type"),
        )
    )
    angle = _content_angle(cluster_intent, ctype)
    priority = _content_priority(total_volume, confidence / 100.0, len(keyword_items))

    variations = [it["keyword"] for it in keyword_items if normalize_intent_label(str(it.get("intent") or "")) == cluster_intent]
    if not variations:
        variations = [it["keyword"] for it in keyword_items]
    supporting = [
        it["keyword"]
        for it in keyword_items
        if it["content_role"] in ("secondary", "semantic", "supporting")
        and normalize_intent_label(str(it.get("intent") or "")) == cluster_intent
    ][:12]

    content_plan = build_content_plan(
        cluster_id=str(raw.get("cluster_id") or f"cluster_{idx + 1}"),
        topic=topic,
        main_kw=main_kw,
        keyword_items=keyword_items,
        cluster_intent=cluster_intent,
        suggested_content_type=ctype,
        content_angle=angle,
        total_volume=total_volume,
        confidence_score=confidence,
    )

    return {
        "cluster_id": raw.get("cluster_id") or f"cluster_{idx + 1}",
        "topic": topic,
        "main_keyword": main_kw,
        "primary_keyword": main_kw,
        "variations": variations,
        "keywords": variations,
        "keyword_items": keyword_items,
        "supporting_keywords": supporting,
        "total_volume": total_volume,
        "total_keyword": len(keyword_items),
        "cluster_size": len(keyword_items),
        "intent": cluster_intent,
        "intent_purity": intent_purity,
        "intent_conflict": intent_conflict,
        "confidence_score": confidence,
        "cohesion_score": raw.get("cohesion_score"),
        "serp_overlap_score": round(serp_avg, 4),
        "shared_urls_count": raw.get("shared_urls_count"),
        "shared_urls_count_min": raw.get("shared_urls_count_min"),
        "shared_urls_count_max": raw.get("shared_urls_count_max"),
        "merge_pair_details": raw.get("merge_pair_details") or [],
        "warning": raw.get("warning"),
        "suggested_content_type": ctype,
        "content_angle": angle,
        "content_priority": priority,
        "content_plan": content_plan,
        "primary_serp_page_type": raw.get("primary_serp_page_type"),
        "detail": {
            "intent_source": raw.get("intent_source"),
            "serp_data_available": bool(explain.get("serp_data_available", True)),
            "merge_pair_details": raw.get("merge_pair_details") or explain.get("merge_pair_details") or [],
            "content_map": {
                "outline_hint": _outline_hint(main_kw, keyword_items, cluster_intent, ctype),
                "supporting_keywords": supporting,
            },
        },
    }


def _outline_hint(main_kw: str, items: list[dict[str, Any]], intent: str, ctype: str) -> str:
    it = normalize_intent_label(intent)
    lines = [f"# {main_kw}", ""]
    secs = [it for it in items if it.get("content_role") in ("secondary", "semantic")][:6]
    faqs = [it for it in items if it.get("content_role") == "faq"][:4]
    if it in ("commercial", "transactional", "local"):
        lines.append("## Giới thiệu dịch vụ / giải pháp")
        lines.append(f"- {main_kw}")
        lines.append("## Lợi ích & quy trình")
    elif it == "informational":
        lines.append(f"## {main_kw} là gì?")
    if secs:
        lines.append("")
        lines.append("## Các mục chính")
        for row in secs:
            lines.append(f"- {row['keyword']}")
    if faqs:
        lines.append("")
        lines.append("## Câu hỏi thường gặp")
        for it in faqs:
            lines.append(f"- {it['keyword']}")
    lines.append("")
    lines.append(f"Intent: {intent} · Định dạng: {ctype}")
    return "\n".join(lines).strip()


def build_content_map_summary(clusters: list[dict[str, Any]]) -> dict[str, Any]:
    total_kw = sum(int(c.get("total_keyword") or len(c.get("keywords") or [])) for c in clusters)
    vols = [c.get("total_volume") for c in clusters if c.get("total_volume") is not None]
    plans = build_content_plans_from_clusters(clusters)
    priorities = [float(p.get("priority_score") or 0) for p in plans]
    return {
        "cluster_count": len(clusters),
        "total_keywords": total_kw,
        "total_volume": int(sum(vols)) if vols else None,
        "articles_suggested": len(clusters),
        "content_plan_count": len(plans),
        "avg_priority_score": round(sum(priorities) / len(priorities), 1) if priorities else None,
    }
