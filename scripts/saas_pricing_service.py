"""Build pricing page data from plans + usage_limits (DB-driven)."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.services import plan_service

FEATURE_LABELS: dict[str, str] = {
    "content_ai_article": "Đăng bài Content AI",
    "content_ai_bulk_article": "Bulk Content AI",
    "technical_audit": "Check Technical SEO",
    "seo_score": "Chấm điểm SEO URL",
    "keyword_research": "Research từ khóa",
    "keyword_cluster": "Gom nhóm từ khóa",
    "internal_link": "Internal Links",
    "schema_generate": "Sinh Schema JSON-LD",
    "wp_publish": "Đăng WordPress",
    "image_generate": "Ảnh AI",
    "chatbot_message": "Tin nhắn chatbot",
    "knowledge_base_search": "Tìm Knowledge Base",
    "wordpress_site": "Website WordPress",
    "google_search_console": "Google Search Console",
}

PERIOD_LABELS: dict[str, str] = {
    "monthly": "tháng",
    "daily": "ngày",
    "yearly": "năm",
    "lifetime": "toàn kỳ dùng thử",
    "none": "",
}

# 4 cột pricing: Free trial 5d → Basic → Pro → Agency (không Unlimited)
PRICING_SLUG_ORDER: list[str] = ["free_trial_5d", "starter", "pro", "agency"]
PUBLIC_PRICING_SLUGS = frozenset(PRICING_SLUG_ORDER)

FREE_TRIAL_5D_DISPLAY: dict = {
    "plan_kind": "free_trial",
    "trial_days": 5,
    "byok_note": "Yêu cầu API key cá nhân",
    "display_rows": [
        {"included": True, "label": "1 project"},
        {"included": True, "label": "25 bài viết AI / 5 ngày"},
        {"included": True, "label": "Tối đa 5 bài / ngày"},
        {"included": True, "label": "Check Technical SEO 5 lần"},
        {"included": True, "label": "Research 3.000 keyword"},
        {"included": True, "label": "Gom nhóm 500 keyword"},
        {"included": True, "label": "Chèn 20 ảnh"},
        {"included": False, "label": "Internal Link tự động"},
        {"included": False, "label": "Google Search Console"},
        {"included": False, "label": "Bulk Content AI"},
        {"included": False, "label": "Hỗ trợ ưu tiên"},
    ],
}

PAID_PLAN_DISPLAY: dict[str, dict] = {
    "starter": {
        "articles": "50 articles/month",
        "projects": "3 projects",
        "devices": "2 devices",
        "gsc": True,
        "priority_support": False,
    },
    "pro": {
        "articles": "100 articles/month",
        "projects": "10 projects",
        "devices": "3 devices",
        "gsc": True,
        "priority_support": False,
    },
    "agency": {
        "articles": "500 articles/month",
        "projects": "50 projects",
        "devices": "4 devices",
        "gsc": True,
        "priority_support": True,
    },
}

PAID_FEATURE_ROWS: list[tuple[str, str]] = [
    ("ai_write", "AI article writing"),
    ("ai_image", "AI image generation"),
    ("wp_pub", "WordPress publishing"),
    ("internal_links", "Internal Links"),
    ("knowledge", "knowledge_base"),
    ("gsc", "Google Search Console"),
    ("priority", "Priority support"),
]


def feature_label(feature_key: str) -> str:
    key = str(feature_key or "").strip()
    return FEATURE_LABELS.get(key, key.replace("_", " ").title())


def format_limit_display(limit_value: int, is_hard_limit: bool, period: str) -> str:
    period_lbl = PERIOD_LABELS.get(str(period or "monthly"), str(period or ""))
    suffix = f" / {period_lbl}" if period_lbl else ""

    if int(limit_value) == -1:
        return f"Không giới hạn{suffix}"
    if int(limit_value) == 0 and bool(is_hard_limit):
        return "Không bao gồm trong gói"
    return f"{int(limit_value):,}{suffix}".replace(",", ".")


def format_price_vnd(amount: int, currency: str = "VND") -> str:
    cur = (currency or "VND").upper()
    if cur == "VND":
        return f"{int(amount):,} ₫".replace(",", ".")
    return f"{int(amount):,} {cur}".replace(",", ".")


def format_billing_cycle_label(billing_cycle: str) -> str:
    cycle = str(billing_cycle or "").strip().lower()
    if cycle == "none":
        return "Dùng thử — không thu phí định kỳ"
    if cycle == "monthly":
        return "Thanh toán theo tháng"
    if cycle == "yearly":
        return "Thanh toán theo năm"
    return cycle or "—"


def _parse_metadata(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _paid_feature_flags(slug: str) -> dict[str, bool]:
    cfg = PAID_PLAN_DISPLAY.get(slug, {})
    return {
        "ai_write": True,
        "ai_image": True,
        "wp_pub": True,
        "internal_links": True,
        "knowledge": True,
        "gsc": bool(cfg.get("gsc")),
        "priority": bool(cfg.get("priority_support")),
    }


def get_pricing_plans(db: Session) -> list[dict]:
    """Public catalog: Dùng tool 5 ngày miễn phí + Basic + Pro + Agency (4 cột)."""
    cards_by_slug: dict[str, dict] = {}

    for plan in plan_service.list_active_plans(db, public_only=True):
        if plan.slug not in PUBLIC_PRICING_SLUGS:
            continue

        full = plan_service.get_plan_with_limits(db, plan.id) or plan
        limits = sorted(
            getattr(full, "usage_limits", None) or plan_service.get_limits_for_plan(db, plan.id),
            key=lambda ul: ul.feature_key,
        )
        features = [
            {
                "feature_key": ul.feature_key,
                "label": feature_label(ul.feature_key),
                "display": format_limit_display(ul.limit_value, ul.is_hard_limit, ul.period),
            }
            for ul in limits
        ]

        meta = _parse_metadata(getattr(plan, "metadata_json", None))
        card: dict = {
            "id": plan.id,
            "slug": plan.slug,
            "name": plan.name,
            "description": plan.description or "",
            "price_amount": int(plan.price_amount),
            "price_display": format_price_vnd(plan.price_amount, plan.currency),
            "currency": plan.currency,
            "billing_cycle": plan.billing_cycle,
            "billing_label": format_billing_cycle_label(plan.billing_cycle),
            "is_highlight": plan.slug == "pro",
            "features": features,
            "quota_meta": {},
            "feature_flags": {},
            "feature_rows": [],
            "plan_kind": "paid",
            "trial_days": int(meta.get("trial_days") or 0) or None,
            "byok_note": str(meta.get("note") or "").strip() or None,
        }

        if plan.slug == "free_trial_5d":
            card["plan_kind"] = "free_trial"
            card["trial_days"] = int(meta.get("trial_days") or FREE_TRIAL_5D_DISPLAY["trial_days"])
            card["byok_note"] = (
                str(meta.get("note") or "").strip() or FREE_TRIAL_5D_DISPLAY["byok_note"]
            )
            card["display_rows"] = list(FREE_TRIAL_5D_DISPLAY["display_rows"])
            card["feature_rows"] = []
        elif plan.slug in PAID_PLAN_DISPLAY:
            card["quota_meta"] = dict(PAID_PLAN_DISPLAY[plan.slug])
            card["feature_flags"] = _paid_feature_flags(plan.slug)
            card["feature_rows"] = [
                {"key": k, "label": lbl, "included": card["feature_flags"].get(k, False)}
                for k, lbl in PAID_FEATURE_ROWS
            ]

        cards_by_slug[plan.slug] = card

    return [cards_by_slug[slug] for slug in PRICING_SLUG_ORDER if slug in cards_by_slug]
