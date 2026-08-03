"""Canonical plan quota & feature matrix — Basic / Pro / Agency / Business.

Single source of truth for:
- usage_limits rows (monthly subscription quota)
- lead scanner limits, chatbot limits
- pricing catalog compare flags
- feature gates (Google Map SEO, keyword nâng cao, white-label, …)

Credit wallet is separate: quota caps feature usage; credits pay per expensive API call.
"""

from __future__ import annotations

from typing import Any

PAID_PLAN_SLUGS: tuple[str, ...] = ("starter", "pro", "agency", "business")

PLAN_DISPLAY_NAMES: dict[str, str] = {
    "starter": "Basic",
    "pro": "Pro",
    "agency": "Agency",
    "business": "Business",
    "admin": "Admin",
    "free_trial_5d": "Dùng thử 5 ngày",
}

# User-facing quota keys → usage_limits.feature_key
FEATURE_KEYS: dict[str, str] = {
    "projects": "wordpress_site",
    "ai_articles": "content_ai_article",
    "technical_audit": "technical_audit",
    "seo_score": "seo_score",
    "keyword_research": "keyword_research",
    "lead_scan": "lead_map_scan",
    "lead_detail": "lead_map_place_detail",
    "chatbot_reply": "chatbot_cskh_reply",
    "google_map_location": "google_map_location",
    "team_members": "platform_users",
}

FEATURE_LABELS_VI: dict[str, str] = {
    "projects": "Website/Project",
    "ai_articles": "Bài AI/tháng",
    "technical_audit": "Technical Audit/tháng",
    "seo_score": "URL SEO Score/tháng",
    "keyword_research": "Keyword Research/tháng",
    "lead_scan": "Lead scan/tháng",
    "lead_detail": "Lead detail (SĐT)/tháng",
    "chatbot_reply": "Chatbot AI reply/tháng",
    "google_map_location": "Google Map location",
    "team_members": "User/team member",
}

FEATURE_KEY_LABELS_VI: dict[str, str] = {
    FEATURE_KEYS[k]: v for k, v in FEATURE_LABELS_VI.items()
}

# Monthly numeric quotas per paid plan (starter = Basic)
PLAN_MONTHLY_QUOTAS: dict[str, dict[str, int]] = {
    "starter": {
        "projects": 3,
        "ai_articles": 30,
        "technical_audit": 10,
        "seo_score": 50,
        "keyword_research": 2500,
        "lead_scan": 30,
        "lead_detail": 20,
        "chatbot_reply": 500,
        "google_map_location": 0,
        "team_members": 1,
    },
    "pro": {
        "projects": 8,
        "ai_articles": 80,
        "technical_audit": 25,
        "seo_score": 150,
        "keyword_research": 4000,
        "lead_scan": 100,
        "lead_detail": 100,
        "chatbot_reply": 3000,
        "google_map_location": 5,
        "team_members": 3,
    },
    "agency": {
        "projects": 20,
        "ai_articles": 200,
        "technical_audit": 60,
        "seo_score": 500,
        "keyword_research": 8000,
        "lead_scan": 300,
        "lead_detail": 300,
        "chatbot_reply": 15000,
        "google_map_location": 25,
        "team_members": 5,
    },
    "business": {
        "projects": 50,
        "ai_articles": 500,
        "technical_audit": 150,
        "seo_score": 2500,
        "keyword_research": 20000,
        "lead_scan": 600,
        "lead_detail": 600,
        "chatbot_reply": 50000,
        "google_map_location": 100,
        "team_members": 10,
    },
}

# Lead scanner: daily cap derived from monthly (≈ monthly/10, min 1)
LEAD_SCANNER_MAX_RESULTS: dict[str, int] = {
    "starter": 20,
    "pro": 50,
    "agency": 100,
    "business": 100,
    "free": 20,
    "admin": 100,
}

LEAD_SCANNER_DAILY_SCANS: dict[str, int] = {
    "starter": 3,
    "pro": 10,
    "agency": 25,
    "business": 50,
    "free": 1,
    "admin": 999,
}

# Chatbot bots (separate from reply quota)
CHATBOT_BOT_LIMITS: dict[str, int] = {
    "starter": 1,
    "pro": 3,
    "agency": 15,
    "business": 50,
    "admin": 999,
}

# Plan capability flags (not simple counts)
PLAN_FEATURES: dict[str, dict[str, Any]] = {
    "starter": {
        "byok_preferred": False,
        "google_map_seo": False,
        "kw_advanced": False,
        "kw_serp_hybrid": False,
        "chatbot_enabled": True,
        "chatbot_facebook": False,
        "white_label_report": False,
        "report_client": False,
        "priority_worker": "Cơ bản",
        "support": "Cơ bản",
        "platform_gsc": True,
        "platform_ga4": False,
    },
    "pro": {
        "byok_preferred": False,
        "google_map_seo": True,
        "kw_advanced": True,
        "kw_serp_hybrid": True,
        "chatbot_enabled": True,
        "chatbot_facebook": True,
        "white_label_report": False,
        "report_client": False,
        "priority_worker": "Ưu tiên",
        "support": "Ưu tiên",
        "platform_gsc": True,
        "platform_ga4": True,
    },
    "agency": {
        "byok_preferred": False,
        "google_map_seo": True,
        "kw_advanced": True,
        "kw_serp_hybrid": True,
        "chatbot_enabled": True,
        "chatbot_facebook": True,
        "white_label_report": True,
        "report_client": True,
        "priority_worker": "Cao",
        "support": "Ưu tiên cao",
        "platform_gsc": True,
        "platform_ga4": True,
    },
    "business": {
        "byok_preferred": False,
        "google_map_seo": True,
        "kw_advanced": True,
        "kw_serp_hybrid": True,
        "chatbot_enabled": True,
        "chatbot_facebook": True,
        "white_label_report": True,
        "report_client": True,
        "priority_worker": "Cao nhất",
        "support": "Riêng / ưu tiên nhất",
        "platform_gsc": True,
        "platform_ga4": True,
    },
}

# Free trial 5d — demo BYOK, quota thấp (không burn API pool)
FREE_TRIAL_USAGE_LIMITS: list[tuple[str, str, int, str, bool]] = [
    ("free_trial_5d", "wordpress_site", 1, "lifetime", True),
    ("free_trial_5d", "content_ai_article", 10, "lifetime", True),
    ("free_trial_5d", "content_ai_brief", 30, "lifetime", True),
    ("free_trial_5d", "content_ai_article", 3, "daily", True),
    ("free_trial_5d", "technical_audit", 3, "lifetime", True),
    ("free_trial_5d", "keyword_research", 200, "lifetime", True),
    ("free_trial_5d", "keyword_cluster", 50, "lifetime", True),
    ("free_trial_5d", "seo_score", 5, "lifetime", True),
    ("free_trial_5d", "lead_map_scan", 2, "lifetime", True),
    ("free_trial_5d", "lead_map_place_detail", 0, "lifetime", True),
    ("free_trial_5d", "image_generate", 5, "lifetime", True),
    ("free_trial_5d", "internal_link", 0, "lifetime", True),
    ("free_trial_5d", "google_search_console", 0, "lifetime", True),
    ("free_trial_5d", "content_ai_bulk_article", 0, "lifetime", True),
    ("free_trial_5d", "wp_publish", 0, "lifetime", True),
    ("free_trial_5d", "index_control_submit", 3, "lifetime", True),
]

# Extra usage_limits not in PLAN_MONTHLY_QUOTAS (unchanged from legacy seed)
LEGACY_USAGE_LIMITS: list[tuple[str, str, int, str, bool]] = [
    ("starter", "content_ai_brief", 120, "monthly", True),
    ("starter", "content_ai_bulk_article", 10, "monthly", True),
    ("starter", "image_generate", 20, "monthly", True),
    ("starter", "wp_publish", 15, "monthly", True),
    ("starter", "internal_link", 1, "monthly", True),
    ("starter", "social_auto", 15, "monthly", True),
    ("starter", "google_search_console", 1, "monthly", True),
    ("starter", "index_control_submit", 30, "monthly", True),
    ("pro", "content_ai_brief", 320, "monthly", True),
    ("pro", "content_ai_bulk_article", 40, "monthly", True),
    ("pro", "image_generate", 40, "monthly", True),
    ("pro", "wp_publish", 40, "monthly", True),
    ("pro", "internal_link", 1, "monthly", True),
    ("pro", "social_auto", 40, "monthly", True),
    ("pro", "index_control_submit", 120, "monthly", True),
    ("agency", "content_ai_brief", 1000, "monthly", True),
    ("agency", "content_ai_bulk_article", 100, "monthly", True),
    ("agency", "image_generate", 120, "monthly", True),
    ("agency", "wp_publish", 120, "monthly", True),
    ("agency", "internal_link", 1, "monthly", True),
    ("agency", "social_auto", 120, "monthly", True),
    ("agency", "index_control_submit", 500, "monthly", True),
    ("business", "content_ai_brief", 2500, "monthly", True),
    ("business", "content_ai_bulk_article", 300, "monthly", True),
    ("business", "image_generate", 400, "monthly", True),
    ("business", "wp_publish", 400, "monthly", True),
    ("business", "internal_link", 1, "monthly", True),
    ("business", "social_auto", 400, "monthly", True),
    ("business", "index_control_submit", 2000, "monthly", True),
]


def feature_key_for(quota_key: str) -> str:
    return FEATURE_KEYS.get(quota_key, quota_key)


def monthly_quota(plan_slug: str, quota_key: str) -> int:
    slug = str(plan_slug or "").strip().lower()
    return int(PLAN_MONTHLY_QUOTAS.get(slug, {}).get(quota_key, 0))


def plan_feature(plan_slug: str | None, key: str, default: Any = False) -> Any:
    slug = str(plan_slug or "").strip().lower()
    return PLAN_FEATURES.get(slug, {}).get(key, default)


def chatbot_bot_limit(plan_slug: str | None) -> int:
    slug = str(plan_slug or "").strip().lower()
    return int(CHATBOT_BOT_LIMITS.get(slug, 0))


def chatbot_monthly_reply_limit(plan_slug: str | None) -> int:
    return monthly_quota(str(plan_slug or ""), "chatbot_reply")


def lead_scanner_limits(plan_slug: str | None) -> dict[str, int]:
    slug = str(plan_slug or "free").strip().lower()
    monthly = monthly_quota(slug, "lead_scan") if slug in PLAN_MONTHLY_QUOTAS else 5
    if slug == "admin":
        monthly = 9999
    elif slug == "free" or slug not in PLAN_MONTHLY_QUOTAS:
        monthly = 5
    daily = int(LEAD_SCANNER_DAILY_SCANS.get(slug, max(1, monthly // 10)))
    max_results = int(LEAD_SCANNER_MAX_RESULTS.get(slug, 20))
    return {
        "daily_scans": daily,
        "monthly_scans": monthly,
        "max_results": max_results,
    }


def iter_usage_limits() -> list[tuple[str, str, int, str, bool]]:
    """All usage_limits rows for DB seed / migration."""
    rows: list[tuple[str, str, int, str, bool]] = []
    rows.extend(FREE_TRIAL_USAGE_LIMITS)
    rows.extend(LEGACY_USAGE_LIMITS)
    for slug, quotas in PLAN_MONTHLY_QUOTAS.items():
        for qkey, limit in quotas.items():
            fk = feature_key_for(qkey)
            rows.append((slug, fk, int(limit), "monthly", True))
    return rows


def compare_patch_for_plan(slug: str) -> dict[str, Any]:
    """Merge registry values into pricing catalog compare dict."""
    quotas = PLAN_MONTHLY_QUOTAS.get(slug, {})
    feats = PLAN_FEATURES.get(slug, {})
    return {
        "platform_users": quotas.get("team_members", 0),
        "platform_projects": quotas.get("projects", 0),
        "content_ai_per_month": quotas.get("ai_articles", 0),
        "audit_technical": quotas.get("technical_audit", 0),
        "audit_seo_score": quotas.get("seo_score", 0),
        "kw_advanced": bool(feats.get("kw_advanced")),
        "kw_serp_hybrid": bool(feats.get("kw_serp_hybrid")),
        "report_whitelabel": bool(feats.get("white_label_report")),
        "report_client": bool(feats.get("report_client")),
        "priority_worker": str(feats.get("priority_worker") or ""),
        "support": str(feats.get("support") or ""),
        "platform_gsc": bool(feats.get("platform_gsc")),
        "platform_ga4": bool(feats.get("platform_ga4")),
        "google_map_seo": bool(feats.get("google_map_seo")),
        "google_map_locations": quotas.get("google_map_location", 0),
        "lead_scan_monthly": quotas.get("lead_scan", 0),
        "lead_detail_monthly": quotas.get("lead_detail", 0),
        "chatbot_reply_monthly": quotas.get("chatbot_reply", 0),
        "chatbot_bots": chatbot_bot_limit(slug),
        "byok_preferred": bool(feats.get("byok_preferred")),
        "chatbot_facebook": bool(feats.get("chatbot_facebook")),
    }


def catalog_for_api() -> list[dict[str, Any]]:
    """Public quota catalog per plan for /saas/plan-quota-catalog."""
    out: list[dict[str, Any]] = []
    for slug in PAID_PLAN_SLUGS:
        quotas = PLAN_MONTHLY_QUOTAS.get(slug, {})
        feats = PLAN_FEATURES.get(slug, {})
        items = [
            {"key": k, "label": FEATURE_LABELS_VI.get(k, k), "limit": quotas.get(k, 0), "period": "monthly"}
            for k in FEATURE_KEYS
        ]
        lead = lead_scanner_limits(slug)
        out.append({
            "plan_slug": slug,
            "plan_name": PLAN_DISPLAY_NAMES.get(slug, slug),
            "quotas": items,
            "lead_scanner": lead,
            "chatbot_bots": chatbot_bot_limit(slug),
            "features": feats,
        })
    return out
