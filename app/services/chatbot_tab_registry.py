"""Định nghĩa 4 tab chính Chatbot AI — workflow, credit, progress."""

from __future__ import annotations

from typing import Any

INTENT_QUICK_KEYWORD_ARTICLE = "quick_keyword_article"
INTENT_KEYWORD_CLUSTER_TO_ARTICLE = "keyword_cluster_to_article"
INTENT_KEYWORD_RESEARCH = "keyword_research"
INTENT_KEYWORD_RESEARCH_CLUSTER = "keyword_research_cluster"
INTENT_URL_SEO_SCOREBOARD = "url_seo_scoreboard"
INTENT_CONTENT_SEO_SCORE = "content_seo_score"
INTENT_TECHNICAL_QUICK_AUDIT = "technical_quick_audit"
INTENT_TECHNICAL_DEEP_AUDIT = "technical_deep_audit"
INTENT_TECHNICAL_SINGLE_URL = "technical_single_url"
# Legacy alias
INTENT_TECHNICAL_AUDIT = INTENT_TECHNICAL_DEEP_AUDIT

TAB_WRITE = "write"
TAB_SEO_SCORE = "seo_score"
TAB_TECHNICAL = "technical"
TAB_RESEARCH = "research"

_WRITE_PROGRESS: tuple[tuple[str, str], ...] = (
    ("outline", "Tạo outline theo SEO Score"),
    ("credits", "Tính credit"),
    ("writing", "Viết bài chuẩn SEO"),
    ("word_count", "Kiểm tra số từ"),
    ("seo_score", "Chấm 30 yếu tố SEO Score"),
    ("seo_rewrite", "Tối ưu lại bài viết"),
    ("images", "Chèn hình ảnh"),
    ("complete", "Hoàn tất"),
)

PROGRESS_BY_INTENT: dict[str, tuple[tuple[str, str], ...]] = {
    INTENT_QUICK_KEYWORD_ARTICLE: _WRITE_PROGRESS,
    INTENT_KEYWORD_CLUSTER_TO_ARTICLE: _WRITE_PROGRESS,
    INTENT_KEYWORD_RESEARCH: (
        ("research", "Research từ khóa"),
        ("complete", "Hoàn thành"),
    ),
    INTENT_KEYWORD_RESEARCH_CLUSTER: (
        ("research", "Research từ khóa"),
        ("clustering", "Gom nhóm từ khóa"),
        ("planning", "Gợi ý title & outline"),
        ("complete", "Hoàn thành"),
    ),
    INTENT_URL_SEO_SCOREBOARD: (
        ("crawl", "Crawl URL"),
        ("analyze", "Phân tích SEO Onpage"),
        ("complete", "Hoàn thành"),
    ),
    INTENT_CONTENT_SEO_SCORE: (
        ("analyze", "Phân tích nội dung"),
        ("complete", "Hoàn thành"),
    ),
    INTENT_TECHNICAL_QUICK_AUDIT: (
        ("crawl", "Crawl nhanh"),
        ("analyze", "Kiểm tra lỗi cơ bản"),
        ("complete", "Hoàn thành"),
    ),
    INTENT_TECHNICAL_DEEP_AUDIT: (
        ("crawl", "Crawl nhiều trang"),
        ("analyze", "Phân tích chi tiết"),
        ("saving", "Lưu báo cáo"),
        ("complete", "Hoàn thành"),
    ),
    INTENT_TECHNICAL_SINGLE_URL: (
        ("fetch", "Lấy dữ liệu URL"),
        ("analyze", "Kiểm tra technical"),
        ("complete", "Hoàn thành"),
    ),
}

CHATBOT_TABS: list[dict[str, Any]] = [
    {
        "id": TAB_WRITE,
        "label": "Viết bài SEO",
        "icon": "✍️",
        "workflows": [
            {
                "id": INTENT_QUICK_KEYWORD_ARTICLE,
                "title": "Viết nhanh theo từ khóa",
                "description": "Chỉ nhập từ khóa chính — AI tạo title, meta, outline và viết bài (credit thấp hơn).",
            },
            {
                "id": INTENT_KEYWORD_CLUSTER_TO_ARTICLE,
                "title": "Viết bài chuyên sâu",
                "description": "Tự research, gom cụm, lấy từ khóa phụ và viết bài SEO chuẩn (credit đầy đủ).",
            },
        ],
    },
    {
        "id": TAB_SEO_SCORE,
        "label": "SEO Score",
        "icon": "📊",
        "workflows": [
            {
                "id": INTENT_URL_SEO_SCOREBOARD,
                "title": "Chấm điểm URL",
                "description": "Nhập URL + từ khóa chính — crawl trang và phân tích SEO Onpage.",
            },
            {
                "id": INTENT_CONTENT_SEO_SCORE,
                "title": "Chấm điểm nội dung",
                "description": "Dán nội dung bài viết + từ khóa chính — phân tích SEO Core 30 yếu tố.",
            },
        ],
    },
    {
        "id": TAB_TECHNICAL,
        "label": "Technical",
        "icon": "🔧",
        "workflows": [
            {
                "id": INTENT_TECHNICAL_QUICK_AUDIT,
                "title": "Audit nhanh",
                "description": "Nhập URL website — crawl nhanh và kiểm tra lỗi technical cơ bản.",
            },
            {
                "id": INTENT_TECHNICAL_DEEP_AUDIT,
                "title": "Audit chuyên sâu",
                "description": "Nhập URL + số trang crawl — phân tích technical SEO chi tiết và lưu báo cáo.",
            },
            {
                "id": INTENT_TECHNICAL_SINGLE_URL,
                "title": "Kiểm tra URL riêng lẻ",
                "description": "Nhập 1 URL — kiểm tra technical cho trang đó (status, index, canonical, robots…).",
            },
        ],
    },
    {
        "id": TAB_RESEARCH,
        "label": "Từ khóa",
        "icon": "🔍",
        "workflows": [
            {
                "id": INTENT_KEYWORD_RESEARCH,
                "title": "Research từ khóa",
                "description": "Mở rộng từ khóa liên quan theo quốc gia, ngôn ngữ và số lượng (không viết bài).",
            },
            {
                "id": INTENT_KEYWORD_RESEARCH_CLUSTER,
                "title": "Research + gom nhóm",
                "description": "Research keyword, gom cụm, gợi ý title/outline và chuyển sang Viết bài SEO.",
            },
        ],
    },
]


def init_progress_for_intent(intent: str) -> list[dict[str, str]]:
    defs = PROGRESS_BY_INTENT.get(str(intent or "").strip()) or PROGRESS_BY_INTENT[INTENT_URL_SEO_SCOREBOARD]
    return [{"id": sid, "label": label, "status": "pending"} for sid, label in defs]


def tab_for_intent(intent: str) -> str:
    mapping = {
        INTENT_QUICK_KEYWORD_ARTICLE: TAB_WRITE,
        INTENT_KEYWORD_CLUSTER_TO_ARTICLE: TAB_WRITE,
        INTENT_URL_SEO_SCOREBOARD: TAB_SEO_SCORE,
        INTENT_CONTENT_SEO_SCORE: TAB_SEO_SCORE,
        INTENT_TECHNICAL_QUICK_AUDIT: TAB_TECHNICAL,
        INTENT_TECHNICAL_DEEP_AUDIT: TAB_TECHNICAL,
        INTENT_TECHNICAL_SINGLE_URL: TAB_TECHNICAL,
        INTENT_KEYWORD_RESEARCH: TAB_RESEARCH,
        INTENT_KEYWORD_RESEARCH_CLUSTER: TAB_RESEARCH,
    }
    return mapping.get(str(intent or "").strip(), TAB_WRITE)


def _technical_credit(intent: str) -> int:
    from app.services.credits import (
        cost_technical_deep_audit,
        cost_technical_quick_audit,
        cost_technical_single_url,
    )

    if intent == INTENT_TECHNICAL_QUICK_AUDIT:
        return cost_technical_quick_audit()
    if intent == INTENT_TECHNICAL_DEEP_AUDIT:
        return cost_technical_deep_audit()
    if intent == INTENT_TECHNICAL_SINGLE_URL:
        return cost_technical_single_url()
    return cost_technical_deep_audit()


def estimate_workflow_credits(intent: str, params: dict[str, Any]) -> dict[str, int]:
    from app.services.content_ai_image_rules import image_credit_slots, normalize_image_source
    from app.services.credits import (
        cost_chatbot_ai_image,
        cost_chatbot_google_image,
        cost_chatbot_internal_links,
        cost_cluster_sync,
        cost_content_ai_article,
        cost_research_run,
        cost_url_seo_scoreboard,
        cost_content_seo_score,
    )

    intent = str(intent or "").strip()
    p = params or {}

    if intent == INTENT_QUICK_KEYWORD_ARTICLE:
        from app.services.credits import estimate_quick_write_credits

        return estimate_quick_write_credits(
            include_images=bool(p.get("include_images")),
            image_source=p.get("image_source"),
            word_count=p.get("word_count"),
        )

    if intent == INTENT_KEYWORD_CLUSTER_TO_ARTICLE:
        from app.services.credits import estimate_chatbot_workflow_credits

        return estimate_chatbot_workflow_credits(
            include_internal_links=bool(p.get("include_internal_links")),
            include_images=bool(p.get("include_images")),
            image_source=p.get("image_source"),
            word_count=p.get("word_count"),
        )

    if intent == INTENT_KEYWORD_RESEARCH:
        research = cost_research_run()
        return {
            "research": research,
            "clustering": 0,
            "content_ai": 0,
            "internal_links": 0,
            "images": 0,
            "images_google": 0,
            "images_ai": 0,
            "image_slots": 0,
            "total": research,
        }

    if intent == INTENT_KEYWORD_RESEARCH_CLUSTER:
        research = cost_research_run()
        clustering = cost_cluster_sync()
        return {
            "research": research,
            "clustering": clustering,
            "content_ai": 0,
            "internal_links": 0,
            "images": 0,
            "images_google": 0,
            "images_ai": 0,
            "image_slots": 0,
            "total": research + clustering,
        }

    if intent == INTENT_URL_SEO_SCOREBOARD:
        score = cost_url_seo_scoreboard()
        return {
            "research": 0,
            "clustering": 0,
            "content_ai": 0,
            "internal_links": 0,
            "images": 0,
            "images_google": 0,
            "images_ai": 0,
            "seo_score": score,
            "total": score,
        }

    if intent == INTENT_CONTENT_SEO_SCORE:
        score = cost_content_seo_score()
        return {
            "research": 0,
            "clustering": 0,
            "content_ai": 0,
            "internal_links": 0,
            "images": 0,
            "images_google": 0,
            "images_ai": 0,
            "seo_score": score,
            "total": score,
        }

    if intent in (INTENT_TECHNICAL_QUICK_AUDIT, INTENT_TECHNICAL_DEEP_AUDIT, INTENT_TECHNICAL_SINGLE_URL):
        tech = _technical_credit(intent)
        return {
            "research": 0,
            "clustering": 0,
            "content_ai": 0,
            "internal_links": 0,
            "images": 0,
            "images_google": 0,
            "images_ai": 0,
            "technical": tech,
            "total": tech,
        }

    return {"total": 0}


def consume_workflow_credits(
    db,
    *,
    user_id: int,
    intent: str,
    params: dict[str, Any],
    workflow_id: str,
) -> dict[str, int]:
    from app.services.credits import (
        consume_chatbot_workflow_credits,
        consume_credits,
        cost_cluster_sync,
        cost_research_run,
        cost_technical_deep_audit,
        cost_technical_quick_audit,
        cost_technical_single_url,
        cost_url_seo_scoreboard,
        cost_content_seo_score,
        credits_enforced,
    )

    est = estimate_workflow_credits(intent, params)
    if not credits_enforced():
        return {**est, "charged": False}

    intent = str(intent or "").strip()
    note = f"wf={workflow_id[:32]};intent={intent[:40]}"

    if intent == INTENT_QUICK_KEYWORD_ARTICLE:
        from app.services.credits import consume_quick_write_credits

        return consume_quick_write_credits(
            db,
            user_id=user_id,
            primary_keyword=str(params.get("primary_keyword") or ""),
            workflow_id=workflow_id,
            include_images=bool(params.get("include_images")),
            image_source=params.get("image_source"),
            word_count=params.get("word_count"),
        )

    if intent == INTENT_KEYWORD_CLUSTER_TO_ARTICLE:
        return consume_chatbot_workflow_credits(
            db,
            user_id=user_id,
            primary_keyword=str(params.get("primary_keyword") or ""),
            workflow_id=workflow_id,
            include_internal_links=bool(params.get("include_internal_links")),
            include_images=bool(params.get("include_images")),
            image_source=params.get("image_source"),
            word_count=params.get("word_count"),
        )

    if intent == INTENT_KEYWORD_RESEARCH:
        if est.get("research", 0) > 0:
            consume_credits(db, user_id=user_id, amount=est["research"], reason="chatbot_keyword_research", note=note)
        return {**est, "charged": True}

    if intent == INTENT_KEYWORD_RESEARCH_CLUSTER:
        if est.get("research", 0) > 0:
            consume_credits(db, user_id=user_id, amount=est["research"], reason="chatbot_keyword_research", note=note)
        if est.get("clustering", 0) > 0:
            consume_credits(db, user_id=user_id, amount=est["clustering"], reason="chatbot_keyword_cluster", note=note)
        return {**est, "charged": True}

    if intent == INTENT_URL_SEO_SCOREBOARD:
        amt = cost_url_seo_scoreboard()
        if amt > 0:
            consume_credits(db, user_id=user_id, amount=amt, reason="url_seo_scoreboard", note=note)
        return {**est, "charged": True}

    if intent == INTENT_CONTENT_SEO_SCORE:
        amt = cost_content_seo_score()
        if amt > 0:
            consume_credits(db, user_id=user_id, amount=amt, reason="content_seo_score", note=note)
        return {**est, "charged": True}

    if intent == INTENT_TECHNICAL_QUICK_AUDIT:
        amt = cost_technical_quick_audit()
        if amt > 0:
            consume_credits(db, user_id=user_id, amount=amt, reason="technical_quick_audit", note=note)
        return {**est, "charged": True}

    if intent == INTENT_TECHNICAL_DEEP_AUDIT:
        amt = cost_technical_deep_audit()
        if amt > 0:
            consume_credits(db, user_id=user_id, amount=amt, reason="technical_deep_audit", note=note)
        return {**est, "charged": True}

    if intent == INTENT_TECHNICAL_SINGLE_URL:
        amt = cost_technical_single_url()
        if amt > 0:
            consume_credits(db, user_id=user_id, amount=amt, reason="technical_single_url", note=note)
        return {**est, "charged": True}

    return {**est, "charged": False}


def validate_prepare_params(intent: str, params: dict[str, Any]) -> dict[str, Any]:
    """Chuẩn hóa + validate params theo intent."""
    intent = str(intent or "").strip()
    if intent == "technical_audit":
        intent = INTENT_TECHNICAL_DEEP_AUDIT
    raw = dict(params or {})
    out: dict[str, Any] = {}

    if intent in (INTENT_QUICK_KEYWORD_ARTICLE, INTENT_KEYWORD_CLUSTER_TO_ARTICLE):
        pk = str(raw.get("primary_keyword") or raw.get("keyword") or "").strip()
        if len(pk) < 2:
            raise ValueError("Vui lòng nhập từ khóa chính.")
        try:
            if raw.get("word_count") is not None:
                wc = int(raw.get("word_count"))
            elif str(raw.get("word_count_preset") or "").strip() == "custom":
                wc = int(raw.get("word_count_custom") or 1500)
            elif raw.get("word_count_preset"):
                wc = int(raw.get("word_count_preset"))
            else:
                wc = 1500
        except (TypeError, ValueError):
            wc = 1500
        wc = max(300, min(5000, wc))
        img_src = str(raw.get("image_source") or "none").strip().lower()
        if img_src not in ("none", "google", "ai"):
            img_src = "none"
        tone_raw = str(raw.get("tone") or "Chuyên nghiệp").strip() or "Chuyên nghiệp"
        wc_preset = str(raw.get("word_count_preset") or "").strip()
        if wc_preset not in ("800", "1000", "1500", "2000", "custom"):
            wc_preset = str(wc) if str(wc) in ("800", "1000", "1500", "2000") else "custom"
        website_url = str(raw.get("website_url") or raw.get("target_website") or "").strip()
        if website_url and not website_url.lower().startswith(("http://", "https://")):
            website_url = "https://" + website_url.lstrip("/")
        website_url = website_url[:500]
        business_vertical = str(raw.get("business_vertical") or "").strip().lower()[:80]
        out = {
            "primary_keyword": pk[:200],
            "keyword": pk[:200],
            "word_count": wc,
            "word_count_preset": wc_preset,
            "language": str(raw.get("language") or "vi").strip() or "vi",
            "tone": tone_raw[:120],
            "country": str(raw.get("country") or "VN").strip() or "VN",
            "article_type": raw.get("article_type"),
            "include_internal_links": bool(raw.get("include_internal_links")),
            "image_source": img_src,
            "include_images": img_src in ("google", "ai"),
            "website_url": website_url,
            "target_website": website_url[:200],
            "business_vertical": business_vertical or None,
        }
        planning = raw.get("planning_snapshot")
        if isinstance(planning, dict) and planning:
            out["planning_snapshot"] = planning
        return out

    if intent in (INTENT_KEYWORD_RESEARCH, INTENT_KEYWORD_RESEARCH_CLUSTER):
        seed = str(raw.get("seed_keyword") or raw.get("primary_keyword") or "").strip()
        if len(seed) < 2:
            raise ValueError("Vui lòng nhập từ khóa gốc.")
        try:
            max_kw = int(raw.get("max_keywords") or 100)
        except (TypeError, ValueError):
            max_kw = 100
        max_kw = max(20, min(500, max_kw))
        out = {
            "seed_keyword": seed[:200],
            "language": str(raw.get("language") or "vi").strip() or "vi",
            "country": str(raw.get("country") or "VN").strip() or "VN",
            "max_keywords": max_kw,
            "include_clustering": intent == INTENT_KEYWORD_RESEARCH_CLUSTER,
        }
        return out

    if intent == INTENT_URL_SEO_SCOREBOARD:
        url = str(raw.get("url") or "").strip()
        if not url:
            raise ValueError("Vui lòng nhập URL.")
        keyword = str(raw.get("keyword") or raw.get("primary_keyword") or "").strip()
        if len(keyword) < 2:
            raise ValueError("Vui lòng nhập từ khóa chính.")
        out = {
            "url": url[:500],
            "keyword": keyword[:200],
            "primary_keyword": keyword[:200],
        }
        return out

    if intent == INTENT_CONTENT_SEO_SCORE:
        content = str(raw.get("content_html") or raw.get("content") or "").strip()
        if len(content) < 80:
            raise ValueError("Vui lòng dán nội dung bài viết (tối thiểu 80 ký tự).")
        keyword = str(raw.get("primary_keyword") or raw.get("keyword") or "").strip()
        if len(keyword) < 2:
            raise ValueError("Vui lòng nhập từ khóa chính.")
        out = {
            "content_html": content[:200_000],
            "primary_keyword": keyword[:200],
            "title": str(raw.get("title") or "").strip()[:300],
            "meta_description": str(raw.get("meta_description") or "").strip()[:500],
        }
        return out

    if intent == INTENT_TECHNICAL_QUICK_AUDIT:
        url = str(raw.get("url") or "").strip()
        if not url:
            raise ValueError("Vui lòng nhập URL website.")
        out = {"url": url[:500], "max_pages": 10}
        return out

    if intent == INTENT_TECHNICAL_DEEP_AUDIT:
        url = str(raw.get("url") or "").strip()
        if not url:
            raise ValueError("Vui lòng nhập URL website.")
        try:
            max_pages = int(raw.get("max_pages") or 50)
        except (TypeError, ValueError):
            max_pages = 50
        out = {
            "url": url[:500],
            "max_pages": max(5, min(200, max_pages)),
        }
        return out

    if intent == INTENT_TECHNICAL_SINGLE_URL:
        url = str(raw.get("url") or "").strip()
        if not url:
            raise ValueError("Vui lòng nhập URL cần kiểm tra.")
        out = {"url": url[:500], "max_pages": 1}
        return out

    raise ValueError(f"Workflow không hỗ trợ: {intent}")
