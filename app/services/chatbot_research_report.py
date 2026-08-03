"""Chuẩn hóa kết quả Research từ khóa cho panel Chatbot."""

from __future__ import annotations

from typing import Any


def _volume_from_row(row: dict[str, Any]) -> int | None:
    sv = row.get("search_volume")
    if isinstance(sv, dict):
        v = sv.get("avg_monthly")
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
    for key in ("display_volume", "raw_volume"):
        try:
            v = row.get(key)
            if v is not None:
                return int(v)
        except (TypeError, ValueError):
            continue
    return None


def _kd_display(row: dict[str, Any]) -> str:
    kd = row.get("kd")
    if kd is None:
        kd = row.get("difficulty")
    try:
        val = float(kd)
    except (TypeError, ValueError):
        return "—"
    if val <= 1.0:
        val *= 100.0
    return f"{int(round(val))}"


def _trend_display(trend: Any) -> str:
    if not isinstance(trend, dict):
        return "—"
    direction = str(trend.get("direction") or trend.get("trend") or "").strip()
    if direction:
        mapping = {
            "up": "Tăng",
            "down": "Giảm",
            "stable": "Ổn định",
            "rising": "Tăng",
            "falling": "Giảm",
        }
        return mapping.get(direction.lower(), direction)
    pct = trend.get("change_pct")
    if pct is not None:
        try:
            p = float(pct)
            if p > 3:
                return "Tăng"
            if p < -3:
                return "Giảm"
            return "Ổn định"
        except (TypeError, ValueError):
            pass
    return "—"


def _cpc_display(row: dict[str, Any]) -> str:
    try:
        avg = float(row.get("cpc_avg") or 0)
    except (TypeError, ValueError):
        avg = 0.0
    if avg <= 0:
        return "—"
    return f"{avg:,.0f} ₫"


def normalize_keyword_rows(keywords: list[dict[str, Any]], *, limit: int = 100) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in keywords[:limit]:
        kw = str(row.get("keyword") or "").strip()
        if not kw:
            continue
        out.append(
            {
                "keyword": kw,
                "volume": _volume_from_row(row),
                "intent": str(row.get("intent") or "—"),
                "difficulty": _kd_display(row),
                "competition": str(row.get("competition") or "—"),
                "trend": _trend_display(row.get("trend")),
                "cpc": _cpc_display(row),
            }
        )
    return out


def normalize_cluster_rows(clusters: list[dict[str, Any]], *, limit: int = 24) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, c in enumerate(clusters[:limit]):
        primary = str(c.get("primary_keyword") or c.get("main_keyword") or "").strip()
        variations = [str(v).strip() for v in (c.get("variations") or c.get("supporting_keywords") or []) if str(v).strip()]
        secondary = [v for v in variations if v.lower() != primary.lower()]
        plan = c.get("content_plan") if isinstance(c.get("content_plan"), dict) else {}
        cluster_name = str(c.get("cluster_name") or c.get("topic") or primary or f"Cụm {i + 1}").strip()
        kd_raw = c.get("difficulty")
        if kd_raw is None:
            kd_raw = c.get("avg_difficulty")
        kd_label = "—"
        if kd_raw is not None:
            try:
                val = float(kd_raw)
                if val <= 1.0:
                    val *= 100.0
                kd_label = str(int(round(val)))
            except (TypeError, ValueError):
                kd_label = str(kd_raw)

        out.append(
            {
                "cluster_id": str(c.get("cluster_id") or f"cluster_{i + 1}"),
                "cluster_name": cluster_name,
                "primary_keyword": primary,
                "secondary_keywords": secondary[:15],
                "secondary_keywords_text": ", ".join(secondary[:15]),
                "intent": str(c.get("intent") or plan.get("intent") or "—"),
                "total_volume": int(c.get("total_volume") or 0),
                "avg_difficulty": kd_label,
                "suggested_title": str(
                    plan.get("recommended_title") or c.get("recommended_title") or c.get("suggested_title") or ""
                ).strip(),
                "suggested_outline": str(
                    plan.get("outline") or c.get("suggested_outline") or c.get("outline") or ""
                ).strip(),
                "meta_description": str(plan.get("meta_description") or "").strip(),
                "target_word_count": plan.get("target_word_count"),
                "suggested_content_type": str(
                    plan.get("suggested_content_type") or c.get("suggested_content_type") or ""
                ).strip(),
            }
        )
    return out


def build_chatbot_research_report(
    *,
    mode: str,
    seed_keyword: str,
    keywords: list[dict[str, Any]],
    clusters: list[dict[str, Any]] | None = None,
    max_keywords: int = 100,
) -> dict[str, Any]:
    kw_rows = normalize_keyword_rows(keywords, limit=max_keywords)
    cluster_rows = normalize_cluster_rows(clusters or [], limit=24) if clusters else []
    return {
        "mode": mode,
        "seed_keyword": seed_keyword,
        "keywords": kw_rows,
        "clusters": cluster_rows,
        "total_keywords": len(keywords),
        "total_clusters": len(clusters or []),
    }
