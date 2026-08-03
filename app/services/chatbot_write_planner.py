"""Lập kế hoạch viết bài SEO cho tab Chatbot (nhanh / chuyên sâu)."""

from __future__ import annotations

import os
import re
from typing import Any

from app.services.cluster_planning_output import suggested_content_type
from app.services.content_draft_builder import suggest_content_ai_field
from app.services.keyword_clustering_engine import build_keyword_clusters
from app.services.keyword_research_pipeline import build_keyword_research_api_response


def _norm_country(country: str | None) -> str:
    c = str(country or "").strip().upper()
    mapping = {"VN": "vn", "US": "us", "SG": "sg", "TH": "th"}
    if c in mapping:
        return mapping[c]
    return str(country or "vn").strip().lower() or "vn"


def _norm_language(language: str | None) -> str:
    lang = str(language or "vi").strip().lower()
    return lang if lang in {"vi", "en"} else "vi"


def _cluster_max() -> int:
    try:
        return max(20, min(200, int(os.getenv("CHATBOT_WORKFLOW_CLUSTER_MAX", "80"))))
    except (TypeError, ValueError):
        return 80


def _cluster_mode() -> str:
    mode = (os.getenv("CHATBOT_WORKFLOW_CLUSTER_MODE", "tfidf") or "tfidf").strip().lower()
    return mode if mode in {"tfidf", "hybrid", "both"} else "tfidf"


def _fetch_serp() -> bool:
    return (os.getenv("CHATBOT_WORKFLOW_FETCH_SERP", "0") or "0").strip().lower() in ("1", "true", "yes")


def _row_volume(row: dict[str, Any]) -> int:
    sv = row.get("search_volume")
    if isinstance(sv, dict):
        return int(sv.get("avg_monthly") or sv.get("display_volume") or 0)
    try:
        return int(sv or 0)
    except (TypeError, ValueError):
        return 0


def _cluster_from_engine_item(c: dict[str, Any], idx: int, kw_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    members = [str(x.get("keyword") or "").strip() for x in (c.get("keywords") or []) if x.get("keyword")]
    members = list(dict.fromkeys(m for m in members if m))
    primary = str(c.get("main_keyword") or c.get("cluster_name") or (members[0] if members else "")).strip()
    if primary and primary.lower() not in {m.lower() for m in members}:
        members = [primary, *members]
    total_vol = sum(_row_volume(kw_map.get(m.lower(), {})) for m in members)
    return {
        "cluster_id": f"cluster_{idx + 1}",
        "primary_keyword": primary,
        "variations": members,
        "intent": str(c.get("intent") or "informational"),
        "cluster_size": len(members),
        "total_volume": total_vol,
        "score": float(c.get("score") or 0.0),
        "serp_overlap_score": float(c.get("serp_overlap_score") or 0.0),
        "suggested_content_type": str(c.get("suggested_content_type") or ""),
    }


def _pick_best_cluster(clusters: list[dict[str, Any]], seed: str) -> dict[str, Any] | None:
    if not clusters:
        return None
    seed_l = seed.strip().lower()
    scored = sorted(clusters, key=lambda c: float(c.get("score") or 0.0), reverse=True)

    for c in scored:
        pk = str(c.get("primary_keyword") or "").strip().lower()
        if pk == seed_l or seed_l in pk or pk in seed_l:
            return c

    for c in scored:
        vars_l = [str(v).strip().lower() for v in (c.get("variations") or []) if str(v).strip()]
        if seed_l in vars_l:
            return c
        for v in vars_l:
            if seed_l in v or v in seed_l:
                return c

    return scored[0]


def _build_outline(
    *,
    primary_keyword: str,
    secondary_keywords: list[str],
    intent: str,
    article_type: str | None,
    title: str = "",
    target_website: str = "",
    website_context: dict[str, Any] | None = None,
    target_word_count: int = 1000,
) -> str:
    from app.services.content_ai_publish_checklist import build_seo_score_writing_brief

    sec_str = ", ".join(secondary_keywords[:15])
    seo_brief = build_seo_score_writing_brief(
        primary_keyword=primary_keyword,
        target_word_count=int(target_word_count or 1000),
        intent=intent,
        target_website=target_website,
        secondary_keywords=secondary_keywords,
    )
    outline = suggest_content_ai_field(
        field="outline_content",
        primary_keyword=primary_keyword,
        secondary_keywords=sec_str,
        title=title,
        target_website=target_website,
        content=seo_brief,
    )
    outline = str(outline or "").strip()
    ctx_block = ""
    if website_context:
        from app.services.chatbot_website_context import format_website_context_block

        ctx_block = format_website_context_block(website_context)
    if outline and ctx_block:
        outline = (
            "<!-- WEBSITE CONTEXT -->\n"
            + ctx_block
            + "\n\n<!-- SEO SCORE BRIEF -->\n"
            + seo_brief
            + "\n\n<!-- OUTLINE -->\n"
            + outline
        )
    elif outline:
        outline = "<!-- SEO SCORE BRIEF -->\n" + seo_brief + "\n\n<!-- OUTLINE -->\n" + outline
    if outline:
        return outline
    lines = ["<!-- SEO SCORE BRIEF -->", seo_brief, f"# {primary_keyword}"]
    if intent:
        lines.append(f"Intent: {intent}")
    if article_type:
        lines.append(f"Loại bài: {article_type}")
    for kw in secondary_keywords[:8]:
        lines.append(f"## {kw}")
    return "\n".join(lines)


def _content_type_from_cluster(cluster: dict[str, Any], article_type: str | None) -> str:
    if article_type:
        return article_type
    suggested = str(cluster.get("suggested_content_type") or "").strip()
    if suggested:
        return suggested
    return suggested_content_type(
        cluster_intent=str(cluster.get("intent") or "informational"),
        primary_serp_page_type=None,
    )


def build_quick_planning(params: dict[str, Any]) -> dict[str, Any]:
    """Viết nhanh: không research, AI gợi ý title/meta/outline."""
    from app.services.chatbot_website_context import prepare_write_params_with_website_context

    params = prepare_write_params_with_website_context(params)
    pk = str(params.get("primary_keyword") or "").strip()
    tone = params.get("tone")
    website_url = str(params.get("website_url") or params.get("target_website") or "")
    website_context = params.get("website_context") if isinstance(params.get("website_context"), dict) else None
    title = suggest_content_ai_field(field="title", primary_keyword=pk, target_website=website_url)
    meta = suggest_content_ai_field(
        field="meta_description", primary_keyword=pk, title=title, target_website=website_url
    )
    secondary_raw = suggest_content_ai_field(
        field="secondary_keywords", primary_keyword=pk, target_website=website_url
    )
    secondary = [s.strip() for s in re.split(r"[,;]", secondary_raw) if s.strip()]
    outline = _build_outline(
        primary_keyword=pk,
        secondary_keywords=secondary,
        intent="informational",
        article_type=params.get("article_type"),
        title=title,
        target_website=website_url,
        website_context=website_context,
        target_word_count=int(params.get("word_count") or 1000),
    )
    from app.services.content_ai_publish_checklist import build_seo_score_writing_brief

    seo_brief = build_seo_score_writing_brief(
        primary_keyword=pk,
        target_word_count=int(params.get("word_count") or 1000),
        intent="informational",
        target_website=website_url,
        secondary_keywords=secondary,
    )
    return {
        "mode": "quick",
        "primary_keyword": pk,
        "title": title,
        "meta_description": meta,
        "secondary_keywords": secondary,
        "outline": outline,
        "seo_writing_brief": seo_brief,
        "intent": "informational",
        "content_type": params.get("article_type"),
        "search_volume": 0,
        "language": params.get("language"),
        "tone": tone,
        "country": params.get("country"),
        "website_url": website_url,
        "website_context": website_context,
        "planning_guard": params.get("planning_guard"),
    }


def build_deep_planning(params: dict[str, Any]) -> dict[str, Any]:
    """Viết chuyên sâu: research + gom cụm + outline chuẩn SEO."""
    from app.services.chatbot_website_context import prepare_write_params_with_website_context

    params = prepare_write_params_with_website_context(params)
    seed = re.sub(r"\s+", " ", str(params.get("primary_keyword") or "").strip())
    if len(seed) < 2:
        raise ValueError("Vui lòng nhập từ khóa chính.")

    loc_lang = _norm_language(params.get("language"))
    loc_country = _norm_country(params.get("country"))
    article_type = params.get("article_type")
    tone = params.get("tone")
    website_url = str(params.get("website_url") or params.get("target_website") or "")
    website_context = params.get("website_context") if isinstance(params.get("website_context"), dict) else None

    research_payload = build_keyword_research_api_response(
        seed_keyword=seed,
        language=loc_lang,
        country=loc_country,
        cluster_mode=_cluster_mode(),
        cluster_fetch_serp=_fetch_serp(),
        cluster_max_keywords=_cluster_max(),
    )
    meta_err = (research_payload.get("meta") or {}).get("error")
    if meta_err:
        raise ValueError(str(meta_err))

    keywords_rows = list(research_payload.get("keywords") or [])
    if not keywords_rows:
        raise ValueError("Không tìm thấy từ khóa liên quan. Thử từ khóa cụ thể hơn.")

    clusters = list(research_payload.get("clusters") or [])
    if not clusters:
        kw_map = {str(r.get("keyword") or "").strip().lower(): r for r in keywords_rows if r.get("keyword")}
        records = [
            {"keyword": str(r.get("keyword") or "").strip(), "source": "chatbot_write_planner"}
            for r in keywords_rows[: _cluster_max()]
            if r.get("keyword")
        ]
        raw_clusters = build_keyword_clusters(
            records,
            fetch_serp=_fetch_serp(),
            serp_country=loc_country,
            serp_language=loc_lang,
        )
        clusters = [_cluster_from_engine_item(c, i, kw_map) for i, c in enumerate(raw_clusters)]

    if not clusters:
        raise ValueError("Không gom được cụm từ khóa. Thử lại với từ khóa ngắn gọn hơn.")

    best = _pick_best_cluster(clusters, seed)
    if not best:
        raise ValueError("Không chọn được cụm từ khóa phù hợp.")

    pk = str(best.get("primary_keyword") or seed).strip()
    variations = [str(v).strip() for v in (best.get("variations") or []) if str(v).strip()]
    secondary = [v for v in variations if v.lower() != pk.lower()][:12]
    intent = str(best.get("intent") or "informational")
    content_type = _content_type_from_cluster(best, article_type)
    title = suggest_content_ai_field(field="title", primary_keyword=pk, target_website=website_url)
    meta = suggest_content_ai_field(
        field="meta_description", primary_keyword=pk, title=title, target_website=website_url
    )
    outline = _build_outline(
        primary_keyword=pk,
        secondary_keywords=secondary,
        intent=intent,
        article_type=article_type,
        title=title,
        target_website=website_url,
        website_context=website_context,
        target_word_count=int(params.get("word_count") or 1000),
    )
    search_vol = int(best.get("total_volume") or 0)
    from app.services.content_ai_publish_checklist import build_seo_score_writing_brief

    seo_brief = build_seo_score_writing_brief(
        primary_keyword=pk,
        target_word_count=int(params.get("word_count") or 1000),
        intent=intent,
        target_website=website_url,
        secondary_keywords=secondary,
    )

    return {
        "mode": "deep",
        "primary_keyword": pk,
        "title": title,
        "meta_description": meta,
        "secondary_keywords": secondary,
        "outline": outline,
        "seo_writing_brief": seo_brief,
        "intent": intent,
        "content_type": content_type,
        "search_volume": search_vol,
        "language": loc_lang,
        "tone": tone,
        "country": loc_country,
        "website_url": website_url,
        "website_context": website_context,
        "planning_guard": params.get("planning_guard"),
        "cluster": {
            "cluster_id": best.get("cluster_id"),
            "primary_keyword": pk,
            "secondary_keywords": secondary,
            "intent": intent,
            "total_volume": search_vol,
            "score": float(best.get("score") or 0.0),
        },
        "keywords_found": len(keywords_rows),
        "clusters_found": len(clusters),
    }


def preview_write_planning(intent: str, params: dict[str, Any]) -> dict[str, Any]:
    from app.services.chatbot_tab_registry import INTENT_KEYWORD_CLUSTER_TO_ARTICLE, INTENT_QUICK_KEYWORD_ARTICLE

    intent = str(intent or "").strip()
    if intent == INTENT_QUICK_KEYWORD_ARTICLE:
        return build_quick_planning(params)
    if intent == INTENT_KEYWORD_CLUSTER_TO_ARTICLE:
        return build_deep_planning(params)
    raise ValueError(f"Intent không hỗ trợ preview outline: {intent}")
