"""SEOAuto pricing catalog: seed + read plans for /pricing.

We store monthly price in plans.price_amount and yearly price + feature matrix in plans.metadata_json.
This keeps billing compatible while letting the pricing page render dynamically.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.plan import Plan
from app.models.subscription import Subscription  # noqa: F401
from app.models.usage_limit import UsageLimit  # noqa: F401
from app.services import plan_service
from app.services.saas_hybrid_pricing import (
    HYBRID_CREDIT_ADDON_NOTES,
    PLAN_MONTHLY_BONUS_CREDITS,
    apply_hybrid_prices_to_pricing_specs,
    build_billing_saas_products,
)
from app.services.plan_quota_registry import (
    PLAN_MONTHLY_QUOTAS,
    chatbot_bot_limit,
    compare_patch_for_plan,
)

logger = logging.getLogger(__name__)


SEOAUTO_PLAN_SLUG_ORDER: list[str] = ["starter", "pro", "agency", "business"]

# Bump when SEOAUTO_PRICING_SPECS / hybrid defaults change — triggers DB metadata sync.
PRICING_CATALOG_REVISION = 7

# Hàng so sánh chi tiết (phần dưới trang /pricing).
PRICING_COMPARE_ROWS: list[dict[str, str]] = [
    {"key": "credits_month", "label": "Credit tặng/tháng"},
    {"key": "platform_projects", "label": "Website/Project"},
    {"key": "content_ai_per_month", "label": "Bài AI/tháng"},
    {"key": "keyword_research_quota", "label": "Keyword Research quota/tháng"},
    {"key": "audit_technical", "label": "Technical Audit/tháng"},
    {"key": "audit_seo_score", "label": "SEO Score URL/tháng"},
    {"key": "kw_advanced", "label": "Keyword DataForSEO nâng cao"},
    {"key": "google_map_seo", "label": "Google Map SEO"},
    {"key": "lead_scan_monthly", "label": "Lead Scanner/tháng"},
    {"key": "chatbot_reply_monthly", "label": "Chatbot CSKH reply/tháng"},
    {"key": "chatbot_bots", "label": "Số chatbot"},
    {"key": "report_whitelabel", "label": "White-label báo cáo"},
    {"key": "content_byok_ai", "label": "Dùng API AI riêng (BYOK)"},
    {"key": "priority_worker", "label": "Ưu tiên xử lý"},
    {"key": "support", "label": "Hỗ trợ"},
]

# Canonical billing SKUs (product_code giữ nguyên cho SePay).
BILLING_SAAS_PRODUCTS: list[dict[str, Any]] = build_billing_saas_products()

BILLING_CREDIT_PRODUCTS: list[dict[str, Any]] = [
    {
        "product_code": "CREDIT_100K",
        "price": 100_000,
        "credits": 1_000,
        "validity_months": 12,
    },
    {
        "product_code": "CREDIT_300K",
        "price": 300_000,
        "credits": 3_300,
        "validity_months": 12,
    },
    {
        "product_code": "CREDIT_500K",
        "price": 500_000,
        "credits": 6_000,
        "validity_months": 12,
    },
    {
        "product_code": "CREDIT_1000K",
        "price": 1_000_000,
        "credits": 13_000,
        "validity_months": 12,
    },
]

BILLING_ARTICLE_PRODUCTS: list[dict[str, Any]] = [
    {
        "product_code": "ARTICLE_ADDON_50",
        "articles": 50,
        "price": 150_000,
        "contact_sales": False,
    },
    {
        "product_code": "ARTICLE_ADDON_100",
        "articles": 100,
        "price": 250_000,
        "contact_sales": False,
    },
    {
        "product_code": "ARTICLE_ADDON_300",
        "articles": 300,
        "price": 600_000,
        "contact_sales": False,
    },
    {
        "product_code": "ARTICLE_ADDON_1000",
        "articles": 1_000,
        "price": None,
        "price_label": "Liên hệ",
        "contact_sales": True,
    },
]

# Backward-compatible aliases used by older callers.
CREDIT_ADDON_PACKAGES: list[dict[str, Any]] = [
    {"price": p["price"], "credits": p["credits"]} for p in BILLING_CREDIT_PRODUCTS
]

CREDIT_ADDON_NOTES: list[str] = list(HYBRID_CREDIT_ADDON_NOTES)

ARTICLE_ADDON_PACKAGES: list[dict[str, Any]] = [
    {
        "articles": p["articles"],
        "price": p.get("price"),
        **({"price_label": p["price_label"]} if p.get("price_label") else {}),
    }
    for p in BILLING_ARTICLE_PRODUCTS
]

ARTICLE_ADDON_NOTES: list[str] = [
    "Gói thêm bài chỉ tăng quota bài viết.",
    "Chi phí API AI do user tự thanh toán qua API riêng.",
    "Nếu dùng API AI của SEOAuto thì trừ thêm credit.",
]

SEOAUTO_PRICING_SPECS: list[dict[str, Any]] = [
    {
        "slug": "starter",
        "name": "Basic",
        "fit": "Cá nhân SEO, chủ shop nhỏ",
        "month_price": 399000,
        "year_price": 3990000,
        "is_popular": False,
        "features": [
            ("User", "1"),
            ("Website/Project", "3"),
            ("Credit/tháng", "500"),
            ("Bài AI/tháng", "30"),
            ("Bulk writer/lần", "10"),
            ("Bài viết lưu tối đa", "200"),
            ("Auto Update", "5 bài/tháng"),
            ("Lên lịch đăng bài", "15 bài/tháng"),
            ("Rank Tracking", "100 keyword"),
            ("Technical Audit", "10 lần/tháng"),
            ("Crawl/lần", "50 URL/tháng"),
            ("SEO Score", "50 URL/tháng"),
        ],
        "cta": "Mua gói Basic",
        "compare": {
            # Nhóm 1 — Nền tảng
            "platform_dashboard": True,
            "platform_users": 1,
            "platform_projects": 3,
            "platform_gsc": True,
            "platform_ga4": False,
            "platform_affiliate": True,
            # Nhóm 2 — Content AI
            "content_single": True,
            "content_bulk": True,
            "content_ai_per_month": 30,
            "content_bulk_per_run": 10,
            "content_saved_max": 200,
            "content_auto_update": 5,
            "content_wp_publish": True,
            "content_schedule": 15,
            "content_byok_ai": False,
            "content_seoauto_ai": True,
            # Nhóm 3 — Keyword & SEO Data
            "kw_basic": True,
            "kw_advanced": False,
            "kw_semantic_cluster": True,
            "kw_serp_hybrid": False,
            "kw_excel": True,
            "kw_rank_tracking": 100,
            # Nhóm 4 — Audit & SEO Score
            "audit_technical": 10,
            "audit_crawl_per_run": 50,
            "audit_seo_score": 50,
            "audit_schema": True,
            "audit_internal_links": True,
            # Nhóm 5 — Social & Report
            "social_posts": 15,
            "report_client": False,
            "report_whitelabel": False,
            "priority_worker": "Cơ bản",
            "support": "Cơ bản",
        },
    },
    {
        "slug": "pro",
        "name": "Pro",
        "fit": "Freelancer, SEO team nhỏ",
        "month_price": 699000,
        "year_price": 6990000,
        "is_popular": True,
        "features": [
            ("User", "3"),
            ("Website/Project", "8"),
            ("Credit/tháng", "2000"),
            ("Bài AI/tháng", "80"),
            ("Bulk writer/lần", "40"),
            ("Bài viết lưu tối đa", "600"),
            ("Auto Update", "20 bài/tháng"),
            ("Lên lịch đăng bài", "40 bài/tháng"),
            ("Rank Tracking", "300 keyword"),
            ("Technical Audit", "25 lần/tháng"),
            ("Crawl/lần", "150 URL/tháng"),
            ("SEO Score", "150 URL/tháng"),
        ],
        "cta": "Bắt đầu với Pro",
        "compare": {
            "platform_dashboard": True,
            "platform_users": 3,
            "platform_projects": 8,
            "platform_gsc": True,
            "platform_ga4": True,
            "platform_affiliate": True,
            "content_single": True,
            "content_bulk": True,
            "content_ai_per_month": 80,
            "content_bulk_per_run": 40,
            "content_saved_max": 600,
            "content_auto_update": 20,
            "content_wp_publish": True,
            "content_schedule": 40,
            "content_byok_ai": False,
            "content_seoauto_ai": True,
            "kw_basic": True,
            "kw_advanced": True,
            "kw_semantic_cluster": True,
            "kw_serp_hybrid": True,
            "kw_excel": True,
            "kw_rank_tracking": 300,
            "audit_technical": 25,
            "audit_crawl_per_run": 150,
            "audit_seo_score": 150,
            "audit_schema": True,
            "audit_internal_links": True,
            "social_posts": 40,
            "report_client": False,
            "report_whitelabel": False,
            "priority_worker": "Ưu tiên",
            "support": "Ưu tiên",
        },
    },
    {
        "slug": "agency",
        "name": "Agency",
        "fit": "Agency SEO",
        "month_price": 1490000,
        "year_price": 14900000,
        "is_popular": False,
        "features": [
            ("User", "5"),
            ("Website/Project", "20"),
            ("Credit/tháng", "6000"),
            ("Bài AI/tháng", "200"),
            ("Bulk writer/lần", "100"),
            ("Bài viết lưu tối đa", "2000"),
            ("Auto Update", "60 bài/tháng"),
            ("Lên lịch đăng bài", "120 bài/tháng"),
            ("Rank Tracking", "1000 keyword"),
            ("Technical Audit", "60 lần/tháng"),
            ("Crawl/lần", "500 URL/tháng"),
            ("SEO Score", "500 URL/tháng"),
            ("White-label report", "Có"),
            ("Ưu tiên worker", "Cao"),
        ],
        "cta": "Nâng cấp gói",
        "compare": {
            "platform_dashboard": True,
            "platform_users": 5,
            "platform_projects": 20,
            "platform_gsc": True,
            "platform_ga4": True,
            "platform_affiliate": True,
            "content_single": True,
            "content_bulk": True,
            "content_ai_per_month": 200,
            "content_bulk_per_run": 100,
            "content_saved_max": 2000,
            "content_auto_update": 60,
            "content_wp_publish": True,
            "content_schedule": 120,
            "content_byok_ai": False,
            "content_seoauto_ai": True,
            "kw_basic": True,
            "kw_advanced": True,
            "kw_semantic_cluster": True,
            "kw_serp_hybrid": True,
            "kw_excel": True,
            "kw_rank_tracking": 1000,
            "audit_technical": 60,
            "audit_crawl_per_run": 500,
            "audit_seo_score": 500,
            "audit_schema": True,
            "audit_internal_links": True,
            "social_posts": 120,
            "report_client": True,
            "report_whitelabel": True,
            "priority_worker": "Cao",
            "support": "Ưu tiên cao",
        },
    },
    {
        "slug": "business",
        "name": "Business",
        "fit": "Công ty, team lớn",
        "month_price": 2990000,
        "year_price": 29900000,
        "is_popular": False,
        "features": [
            ("User", "10"),
            ("Website/Project", "50"),
            ("Credit/tháng", "15000"),
            ("Bài AI/tháng", "500"),
            ("Bulk writer/lần", "300"),
            ("Bài viết lưu tối đa", "8000"),
            ("Auto Update", "200 bài/tháng"),
            ("Lên lịch đăng bài", "400 bài/tháng"),
            ("Rank Tracking", "5000 keyword"),
            ("Technical Audit", "150 lần/tháng"),
            ("Crawl/lần", "2500 URL/tháng"),
            ("SEO Score", "2500 URL/tháng"),
            ("White-label report", "Có"),
            ("Ưu tiên worker", "Cao nhất"),
        ],
        "cta": "Nâng cấp gói",
        "compare": {
            "platform_dashboard": True,
            "platform_users": 10,
            "platform_projects": 50,
            "platform_gsc": True,
            "platform_ga4": True,
            "platform_affiliate": True,
            "content_single": True,
            "content_bulk": True,
            "content_ai_per_month": 500,
            "content_bulk_per_run": 300,
            "content_saved_max": 8000,
            "content_auto_update": 200,
            "content_wp_publish": True,
            "content_schedule": 400,
            "content_byok_ai": False,
            "content_seoauto_ai": True,
            "kw_basic": True,
            "kw_advanced": True,
            "kw_semantic_cluster": True,
            "kw_serp_hybrid": True,
            "kw_excel": True,
            "kw_rank_tracking": 5000,
            "audit_technical": 150,
            "audit_crawl_per_run": 2500,
            "audit_seo_score": 2500,
            "audit_schema": True,
            "audit_internal_links": True,
            "social_posts": 400,
            "report_client": True,
            "report_whitelabel": True,
            "priority_worker": "Cao nhất",
            "support": "Riêng / ưu tiên nhất",
        },
    },
]

apply_hybrid_prices_to_pricing_specs(SEOAUTO_PRICING_SPECS)


def _merge_meta(existing_raw: str | None, update: dict[str, Any]) -> str:
    base: dict[str, Any] = {}
    if existing_raw:
        try:
            v = json.loads(existing_raw)
            if isinstance(v, dict):
                base = v
        except Exception:
            base = {}
    base.update(update)
    return json.dumps(base, ensure_ascii=False)


def _spec_by_slug(slug: str) -> dict[str, Any] | None:
    for spec in SEOAUTO_PRICING_SPECS:
        if spec["slug"] == slug:
            return spec
    return None


def plan_product_codes(plan_slug: str) -> dict[str, str]:
    """Monthly/yearly product_code for a plan slug."""
    out: dict[str, str] = {}
    for product in BILLING_SAAS_PRODUCTS:
        if product["plan_slug"] != plan_slug:
            continue
        cycle = str(product["billing_cycle"])
        out[cycle] = str(product["product_code"])
    return out


def get_billing_product_by_code(product_code: str) -> dict[str, Any] | None:
    code = str(product_code or "").strip().upper()
    if not code:
        return None
    for product in BILLING_SAAS_PRODUCTS:
        if product["product_code"] == code:
            return {"product_type": "saas_plan", **dict(product)}
    for product in BILLING_CREDIT_PRODUCTS:
        if product["product_code"] == code:
            return {"product_type": "credit_addon", **dict(product)}
    for product in BILLING_ARTICLE_PRODUCTS:
        if product["product_code"] == code:
            return {"product_type": "article_addon", **dict(product)}
    return None


def billing_product_display_name(product: dict[str, Any]) -> str:
    ptype = str(product.get("product_type") or "")
    if ptype == "saas_plan":
        cycle = str(product.get("billing_cycle") or "monthly").strip().lower()
        if cycle == "monthly":
            cycle_label = "tháng"
        elif cycle == "semi_annual":
            cycle_label = "6 tháng"
        else:
            cycle_label = "năm"
        return f"{product.get('name') or product.get('plan_slug')} ({cycle_label})"
    if ptype == "credit_addon":
        credits = int(product.get("credits") or 0)
        return f"Credit +{credits:,}".replace(",", ".")
    if ptype == "article_addon":
        articles = int(product.get("articles") or 0)
        return f"+{articles} bài AI/tháng"
    return str(product.get("name") or product.get("product_code") or "Sản phẩm")


def is_billing_product_active(db: Session, product: dict[str, Any]) -> bool:
    """SaaS SKUs require an active public plan; add-ons from catalog are always active."""
    ptype = str(product.get("product_type") or "")
    if ptype != "saas_plan":
        return True
    slug = str(product.get("plan_slug") or "").strip().lower()
    if not slug:
        return False
    plan = plan_service.get_plan_by_slug(db, slug)
    if plan is None:
        logger.warning("billing_product_inactive_missing_plan slug=%s", slug)
        return False
    if not plan.is_active:
        logger.warning("billing_product_inactive_plan slug=%s plan_id=%s", slug, plan.id)
        return False
    return True


def _billing_credit_addons_payload() -> list[dict[str, Any]]:
    return [dict(p) for p in BILLING_CREDIT_PRODUCTS]


def _billing_article_addons_payload() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for product in BILLING_ARTICLE_PRODUCTS:
        row = dict(product)
        if row.get("price_label"):
            row.setdefault("price", None)
        out.append(row)
    return out


def _billing_saas_products_payload() -> list[dict[str, Any]]:
    return [
        {
            "product_code": p["product_code"],
            "product_type": "saas_plan",
            "name": p["name"],
            "plan_slug": p["plan_slug"],
            "billing_cycle": p["billing_cycle"],
            "price": int(p["price"]),
            "currency": p.get("currency") or "VND",
            "period_days": int(p["period_days"]),
            "duration_months": int(
                p.get("duration_months")
                or (6 if p.get("billing_cycle") == "semi_annual" else (14 if p.get("billing_cycle") == "yearly" else 1))
            ),
            "monthly_credit": int(p.get("monthly_credit") or 0),
            "base_credit": int(p.get("base_credit") or 0),
            "bonus_credit": int(p.get("bonus_credit") or 0),
            "total_credit": int(p.get("total_credit") or 0),
        }
        for p in BILLING_SAAS_PRODUCTS
    ]


def _ensure_starter_display_name(db: Session) -> bool:
    """Rename legacy Starter → Basic without touching other plan names."""
    plan = plan_service.get_plan_by_slug(db, "starter")
    if plan is None:
        return False
    if str(plan.name or "").strip() != "Starter":
        return False
    plan.name = "Basic"
    return True


def _ensure_plan_billing_product_codes(db: Session) -> int:
    """Merge billing product codes into plan metadata without overwriting pricing/features."""
    changed = 0
    for slug in SEOAUTO_PLAN_SLUG_ORDER:
        plan = plan_service.get_plan_by_slug(db, slug)
        if plan is None:
            continue
        codes = plan_product_codes(slug)
        if not codes:
            continue
        meta = _parse_meta_raw(plan.metadata_json)
        billing_products = meta.get("billing_products")
        if not isinstance(billing_products, dict):
            billing_products = {}
        want = {
            "monthly": codes.get("monthly"),
            "yearly": codes.get("yearly"),
        }
        if billing_products.get("monthly") == want["monthly"] and billing_products.get("yearly") == want["yearly"]:
            continue
        meta["billing_products"] = want
        plan.metadata_json = json.dumps(meta, ensure_ascii=False)
        changed += 1
    return changed


def ensure_billing_catalog_sync(db: Session) -> dict[str, int]:
    """Idempotent sync: plans exist, starter display name, product codes in metadata."""
    return {
        "plans_ensured": ensure_seoauto_pricing_plans(db),
        "starter_renamed": int(_ensure_starter_display_name(db)),
        "product_codes_merged": _ensure_plan_billing_product_codes(db),
    }


def _parse_meta_raw(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _features_list_to_map(features: list[Any] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in features or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        if not label:
            continue
        out[label] = str(item.get("value") or "").strip()
    return out


def _int_from_text(val: Any) -> int:
    import re

    s = str(val or "").strip().replace(".", "").replace(",", "")
    m = re.search(r"\d+", s)
    return int(m.group()) if m else 0


def _ordered_features(feat_map: dict[str, str], slug: str) -> list[dict[str, str]]:
    spec = _spec_by_slug(slug) or {}
    base_labels = [a for a, _ in spec.get("features") or []]
    ordered: list[dict[str, str]] = []
    seen: set[str] = set()
    for label in base_labels:
        if label in feat_map:
            ordered.append({"label": label, "value": feat_map[label]})
            seen.add(label)
    for label, value in feat_map.items():
        if label not in seen:
            ordered.append({"label": label, "value": value})
    return ordered


def _apply_pricing_spec(db: Session, spec: dict[str, Any], *, force_meta: bool = False) -> bool:
    """Apply one catalog spec to DB. Returns True if anything changed."""
    slug = str(spec["slug"])
    plan = plan_service.get_plan_by_slug(db, slug)
    changed = False
    idx = SEOAUTO_PLAN_SLUG_ORDER.index(slug) + 1 if slug in SEOAUTO_PLAN_SLUG_ORDER else 0

    if plan is None:
        plan = Plan(
            slug=slug,
            name=str(spec["name"]),
            description=str(spec["fit"]),
            price_amount=int(spec["month_price"]),
            currency="VND",
            billing_cycle="monthly",
            is_active=True,
            is_public=True,
            sort_order=idx,
            metadata_json=None,
        )
        db.add(plan)
        db.flush()
        changed = True
    elif force_meta:
        pairs = (
            ("price_amount", int(spec["month_price"])),
            ("description", str(spec["fit"])),
            ("billing_cycle", "monthly"),
            ("currency", "VND"),
            ("is_public", True),
            ("is_active", True),
            ("sort_order", idx),
        )
        for attr, want in pairs:
            if getattr(plan, attr) != want:
                setattr(plan, attr, want)
                changed = True
    else:
        if not plan.is_public:
            plan.is_public = True
            changed = True
        if plan.sort_order != idx:
            plan.sort_order = idx
            changed = True

    meta_payload = {
        "catalog_revision": PRICING_CATALOG_REVISION,
        "year_price": int(spec["year_price"]),
        "semi_annual_price": int(spec.get("semi_annual_price") or 0),
        "semi_annual_total_credit": int(spec.get("semi_annual_total_credit") or 0),
        "semi_annual_bonus_credit": int(spec.get("semi_annual_bonus_credit") or 0),
        "yearly_total_credit": int(spec.get("yearly_total_credit") or 0),
        "yearly_bonus_credit": int(spec.get("yearly_bonus_credit") or 0),
        "is_popular": bool(spec.get("is_popular")),
        "features": [{"label": a, "value": b} for a, b in spec["features"]],
        "cta": str(spec.get("cta") or "Nâng cấp gói"),
        "compare": dict(spec.get("compare") or {}),
    }
    try:
        from app.services.plan_quota_registry import compare_patch_for_plan

        meta_payload["compare"].update(compare_patch_for_plan(slug))
    except Exception:
        logger.debug("compare_patch_for_plan skipped for %s", slug, exc_info=True)
    existing_meta = _parse_meta_raw(plan.metadata_json)
    needs_meta_sync = (
        force_meta
        or not (plan.metadata_json or "").strip()
        or not existing_meta
        or int(existing_meta.get("catalog_revision") or 0) != PRICING_CATALOG_REVISION
    )
    if needs_meta_sync:
        if plan.price_amount != int(spec["month_price"]):
            plan.price_amount = int(spec["month_price"])
            changed = True
        if str(plan.description or "") != str(spec["fit"]):
            plan.description = str(spec["fit"])
            changed = True
        plan.metadata_json = json.dumps(meta_payload, ensure_ascii=False)
        changed = True
    return changed


def admin_pricing_plan_row(db: Session, plan: Plan) -> dict[str, Any]:
    meta = _parse_meta_raw(plan.metadata_json)
    compare = dict(meta.get("compare") or {})
    feat_map = _features_list_to_map(meta.get("features"))

    return {
        "id": int(plan.id),
        "slug": plan.slug,
        "name": plan.name,
        "fit": plan.description or "",
        "month_price": int(plan.price_amount or 0),
        "year_price": int(meta.get("year_price") or 0),
        "credit_per_month": _int_from_text(feat_map.get("Credit/tháng")),
        "users": int(compare.get("platform_users") or _int_from_text(feat_map.get("User")) or 0),
        "projects": int(compare.get("platform_projects") or _int_from_text(feat_map.get("Website/Project")) or 0),
        "ai_articles_per_month": int(
            compare.get("content_ai_per_month") or _int_from_text(feat_map.get("Bài AI/tháng")) or 0
        ),
        "bulk_writer_per_run": int(
            compare.get("content_bulk_per_run") or _int_from_text(feat_map.get("Bulk writer/lần")) or 0
        ),
        "saved_articles_max": int(
            compare.get("content_saved_max") or _int_from_text(feat_map.get("Bài viết lưu tối đa")) or 0
        ),
        "auto_update": int(
            compare.get("content_auto_update") or _int_from_text(feat_map.get("Auto Update")) or 0
        ),
        "rank_tracking": int(
            compare.get("kw_rank_tracking") or _int_from_text(feat_map.get("Rank Tracking")) or 0
        ),
        "technical_audit": int(
            compare.get("audit_technical") or _int_from_text(feat_map.get("Technical Audit")) or 0
        ),
        "crawl_per_run": int(
            compare.get("audit_crawl_per_run") or _int_from_text(feat_map.get("Crawl/lần")) or 0
        ),
        "seo_score": int(
            compare.get("audit_seo_score") or _int_from_text(feat_map.get("SEO Score")) or 0
        ),
        "social_auto": int(
            compare.get("social_posts") or _int_from_text(feat_map.get("Social Auto")) or 0
        ),
        "is_popular": bool(meta.get("is_popular")),
        "is_active": bool(plan.is_active),
    }


def list_admin_pricing_plans(db: Session) -> list[dict[str, Any]]:
    ensure_seoauto_pricing_plans(db)
    db.flush()
    rows: list[dict[str, Any]] = []
    for slug in SEOAUTO_PLAN_SLUG_ORDER:
        plan = plan_service.get_plan_by_slug(db, slug)
        if plan is None:
            continue
        rows.append(admin_pricing_plan_row(db, plan))
    return rows


def update_admin_pricing_plan(db: Session, slug: str, payload: dict[str, Any]) -> dict[str, Any]:
    slug_norm = str(slug or "").strip().lower()
    if slug_norm not in SEOAUTO_PLAN_SLUG_ORDER:
        raise ValueError(f"Plan slug không hợp lệ: {slug}")

    plan = plan_service.get_plan_by_slug(db, slug_norm)
    if plan is None:
        ensure_seoauto_pricing_plans(db)
        db.flush()
        plan = plan_service.get_plan_by_slug(db, slug_norm)
    if plan is None:
        raise ValueError(f"Không tìm thấy plan: {slug_norm}")

    meta = _parse_meta_raw(plan.metadata_json)
    compare = dict(meta.get("compare") or {})
    feat_map = _features_list_to_map(meta.get("features"))

    month_price = max(0, int(payload["month_price"]))
    year_price = max(0, int(payload["year_price"]))
    credit_per_month = max(0, int(payload["credit_per_month"]))
    users = max(0, int(payload["users"]))
    projects = max(0, int(payload["projects"]))
    ai_articles = max(0, int(payload["ai_articles_per_month"]))
    bulk_writer = max(0, int(payload["bulk_writer_per_run"]))
    saved_max = max(0, int(payload["saved_articles_max"]))
    auto_update = max(0, int(payload["auto_update"]))
    rank_tracking = max(0, int(payload["rank_tracking"]))
    technical_audit = max(0, int(payload["technical_audit"]))
    crawl_per_run = max(0, int(payload["crawl_per_run"]))
    seo_score = max(0, int(payload["seo_score"]))
    social_auto = max(0, int(payload["social_auto"]))
    is_popular = bool(payload.get("is_popular"))
    is_active = bool(payload.get("is_active"))

    plan.price_amount = month_price
    plan.is_active = is_active

    compare["platform_users"] = users
    compare["platform_projects"] = projects
    compare["content_ai_per_month"] = ai_articles
    compare["content_bulk_per_run"] = bulk_writer
    compare["content_saved_max"] = saved_max
    compare["content_auto_update"] = auto_update
    compare["kw_rank_tracking"] = rank_tracking
    compare["audit_technical"] = technical_audit
    compare["audit_crawl_per_run"] = crawl_per_run
    compare["audit_seo_score"] = seo_score
    compare["social_posts"] = social_auto

    feat_map["User"] = str(users)
    feat_map["Website/Project"] = str(projects)
    feat_map["Credit/tháng"] = str(credit_per_month)
    feat_map["Bài AI/tháng"] = str(ai_articles)
    feat_map["Bulk writer/lần"] = str(bulk_writer)
    feat_map["Bài viết lưu tối đa"] = str(saved_max)
    feat_map["Auto Update"] = f"{auto_update} bài/tháng"
    feat_map["Rank Tracking"] = f"{rank_tracking} keyword"
    feat_map["Technical Audit"] = f"{technical_audit} lần/tháng"
    feat_map["Crawl/lần"] = f"{crawl_per_run} URL"
    feat_map["SEO Score"] = f"{seo_score} URL/tháng"
    feat_map["Social Auto"] = f"{social_auto} post/tháng"

    plan.metadata_json = _merge_meta(
        plan.metadata_json,
        {
            "year_price": year_price,
            "is_popular": is_popular,
            "features": _ordered_features(feat_map, slug_norm),
            "compare": compare,
        },
    )
    db.flush()
    return admin_pricing_plan_row(db, plan)


def reset_admin_pricing_plans(db: Session, slug: str | None = None) -> int:
    """Reset one or all SEOAuto pricing plans to SEOAUTO_PRICING_SPECS defaults."""
    targets = {slug.strip().lower()} if slug else set(SEOAUTO_PLAN_SLUG_ORDER)
    invalid = targets - set(SEOAUTO_PLAN_SLUG_ORDER)
    if invalid:
        raise ValueError(f"Plan slug không hợp lệ: {', '.join(sorted(invalid))}")

    changed = 0
    for spec in SEOAUTO_PRICING_SPECS:
        if spec["slug"] not in targets:
            continue
        if _apply_pricing_spec(db, spec, force_meta=True):
            changed += 1
    db.flush()
    return changed


def ensure_seoauto_pricing_plans(db: Session) -> int:
    """Ensure the 4 public pricing plans exist without overwriting admin edits."""
    changed = 0
    for spec in SEOAUTO_PRICING_SPECS:
        if _apply_pricing_spec(db, spec, force_meta=False):
            changed += 1
    return changed


def _fmt_vn_num(n: int | float) -> str:
    try:
        return f"{int(n):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(n)


def _build_card_highlights(slug: str, compare: dict[str, Any]) -> list[dict[str, str]]:
    """Thông tin chính hiển thị trên thẻ gói — ngắn gọn, dễ bán."""
    merged = {**compare_patch_for_plan(slug), **(compare or {})}
    quotas = PLAN_MONTHLY_QUOTAS.get(slug, {})
    credits = int(PLAN_MONTHLY_BONUS_CREDITS.get(slug, 0))
    kw_q = int(quotas.get("keyword_research", 0))
    tech_q = int(merged.get("audit_technical") or quotas.get("technical_audit", 0))

    if merged.get("google_map_seo"):
        gmap = f"{_fmt_vn_num(merged.get('google_map_locations', 0))} location"
    else:
        gmap = "Không"

    lead_scan = int(merged.get("lead_scan_monthly") or quotas.get("lead_scan", 0))
    chat_replies = int(merged.get("chatbot_reply_monthly") or quotas.get("chatbot_reply", 0))
    bots = int(merged.get("chatbot_bots") or chatbot_bot_limit(slug))

    rows: list[dict[str, str]] = [
        {"label": "Credit/tháng", "value": _fmt_vn_num(credits)},
        {"label": "Website/Project", "value": _fmt_vn_num(merged.get("platform_projects", 0))},
        {"label": "Bài AI/tháng", "value": _fmt_vn_num(merged.get("content_ai_per_month", 0))},
        {
            "label": "Keyword & Technical",
            "value": f"{_fmt_vn_num(kw_q)} KW · {tech_q} audit",
        },
        {"label": "Google Map SEO", "value": gmap},
        {"label": "Lead Scanner", "value": f"{_fmt_vn_num(lead_scan)} scan/tháng"},
        {"label": "Chatbot CSKH", "value": f"{_fmt_vn_num(chat_replies)} reply · {bots} bot"},
    ]
    if merged.get("report_whitelabel"):
        rows.append({"label": "White-label", "value": "Có"})
    return rows


def _enrich_compare_for_display(slug: str, compare: dict[str, Any]) -> dict[str, Any]:
    merged = {**compare_patch_for_plan(slug), **(compare or {})}
    merged["credits_month"] = int(PLAN_MONTHLY_BONUS_CREDITS.get(slug, 0))
    merged["keyword_research_quota"] = int(PLAN_MONTHLY_QUOTAS.get(slug, {}).get("keyword_research", 0))
    if merged.get("google_map_seo"):
        merged["google_map_seo"] = f"{_fmt_vn_num(merged.get('google_map_locations', 0))} location"
    else:
        merged["google_map_seo"] = False
    return merged


def get_seoauto_pricing_cards(db: Session) -> list[dict[str, Any]]:
    """Return 4 pricing cards from DB; fallback to constants if DB is empty."""
    # Ensure exists; safe idempotent.
    ensure_seoauto_pricing_plans(db)
    db.flush()

    cards: list[dict[str, Any]] = []
    for spec in SEOAUTO_PRICING_SPECS:
        slug = spec["slug"]
        plan = plan_service.get_plan_by_slug(db, slug)
        if plan is None:
            continue
        meta: dict[str, Any] = {}
        if plan.metadata_json:
            try:
                v = json.loads(plan.metadata_json)
                if isinstance(v, dict):
                    meta = v
            except Exception:
                meta = {}

        spec = _spec_by_slug(slug) or {}
        features = list(meta.get("features") or [])
        compare = dict(meta.get("compare") or {})
        if spec and int(meta.get("catalog_revision") or 0) != PRICING_CATALOG_REVISION:
            features = [{"label": a, "value": b} for a, b in spec.get("features") or []]
            compare = dict(spec.get("compare") or {})

        cards.append(
            {
                "slug": plan.slug,
                "name": plan.name,
                "fit": plan.description or "",
                "month_price": int(plan.price_amount or 0),
                "year_price": int(meta.get("year_price") or spec.get("year_price") or 0),
                "semi_annual_price": int(
                    meta.get("semi_annual_price") or spec.get("semi_annual_price") or 0
                ),
                "semi_annual_total_credit": int(
                    meta.get("semi_annual_total_credit") or spec.get("semi_annual_total_credit") or 0
                ),
                "semi_annual_bonus_credit": int(
                    meta.get("semi_annual_bonus_credit") or spec.get("semi_annual_bonus_credit") or 0
                ),
                "yearly_total_credit": int(
                    meta.get("yearly_total_credit") or spec.get("yearly_total_credit") or 0
                ),
                "yearly_bonus_credit": int(
                    meta.get("yearly_bonus_credit") or spec.get("yearly_bonus_credit") or 0
                ),
                "is_popular": bool(meta.get("is_popular") if meta.get("is_popular") is not None else spec.get("is_popular")),
                "badge": "Khuyên dùng" if (meta.get("is_popular") if meta.get("is_popular") is not None else spec.get("is_popular")) else "",
                "cta": str(meta.get("cta") or spec.get("cta") or "Nâng cấp gói"),
                "features": features,
                "highlights": _build_card_highlights(slug, compare),
                "compare": _enrich_compare_for_display(slug, compare),
            }
        )
    # Sort by spec order
    by_slug = {c["slug"]: c for c in cards}
    return [by_slug[s["slug"]] for s in SEOAUTO_PRICING_SPECS if s["slug"] in by_slug]


def get_billing_catalog(db: Session) -> dict[str, Any]:
    """Public billing catalog for /account-billing (plans + add-on packs + product SKUs)."""
    ensure_billing_catalog_sync(db)
    db.flush()

    plans = get_seoauto_pricing_cards(db)
    for idx, plan in enumerate(plans):
        plan["tier"] = idx + 1
        plan["product_codes"] = plan_product_codes(plan["slug"])

    return {
        "plan_slugs": list(SEOAUTO_PLAN_SLUG_ORDER),
        "plans": plans,
        "products": _billing_saas_products_payload(),
        "credit_addons": _billing_credit_addons_payload(),
        "credit_addon_notes": list(CREDIT_ADDON_NOTES),
        "article_addons": _billing_article_addons_payload(),
        "article_addon_notes": list(ARTICLE_ADDON_NOTES),
    }

