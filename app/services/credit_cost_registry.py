"""
Central credit cost registry — một ví credit, giá theo module/action.

Ưu tiên: DB (credit_cost_configs) → env CREDIT_COST_{MODULE}_{ACTION} → DEFAULT_CREDIT_COSTS.
"""

from __future__ import annotations

import os
import re
import threading
import uuid
from typing import Any

from sqlalchemy.orm import Session

_CACHE_LOCK = threading.Lock()
_CONFIG_CACHE: dict[str, dict[str, Any]] | None = None


DEFAULT_CREDIT_COSTS: list[dict[str, Any]] = [
    # Content AI — theo độ dài bài
    {
        "module": "content_ai",
        "action": "article_short",
        "credit_cost": 12,
        "label": "Content AI 700–1000 từ",
        "description": "Viết bài ngắn / gợi ý content field",
    },
    {
        "module": "content_ai",
        "action": "article_medium",
        "credit_cost": 25,
        "label": "Content AI ~1500 từ",
    },
    {
        "module": "content_ai",
        "action": "article_long",
        "credit_cost": 45,
        "label": "Content AI ~2000 từ (35–50 credit)",
    },
    {
        "module": "content_ai",
        "action": "addon_research",
        "credit_cost": 22,
        "label": "Content AI — Deep Research (từ khóa / SERP)",
    },
    {
        "module": "content_ai",
        "action": "addon_outline",
        "credit_cost": 3,
        "label": "Content AI — tạo dàn ý",
    },
    {
        "module": "content_ai",
        "action": "addon_internal_link",
        "credit_cost": 5,
        "label": "Content AI — internal link",
    },
    {
        "module": "content_ai",
        "action": "addon_rewrite",
        "credit_cost": 20,
        "label": "Content AI — viết lại",
    },
    {
        "module": "content_ai",
        "action": "brief_suggest",
        "credit_cost": 2,
        "label": "Gợi ý title/meta/outline",
    },
    {
        "module": "content_ai",
        "action": "google_image",
        "credit_cost": 8,
        "cache_discount_percent": 90,
        "label": "Ảnh Google/CSE",
    },
    {
        "module": "content_ai",
        "action": "ai_image",
        "credit_cost": 52,
        "label": "Ảnh AI Nano Banana (SSOT 50–55 credit/ảnh theo model)",
    },
    # Content Auto Update
    {
        "module": "cau",
        "action": "seo_ai_fix",
        "credit_cost": 10,
        "cache_discount_percent": 85,
        "cache_zero_cost": True,
        "label": "Auto Update — Sửa SEO AI",
    },
    {
        "module": "cau",
        "action": "modal_rewrite",
        "credit_cost": 25,
        "label": "Auto Update — Viết lại content",
    },
    {
        "module": "cau",
        "action": "modal_append",
        "credit_cost": 5,
        "label": "Auto Update — Thêm heading",
    },
    # Keyword / volume
    {
        "module": "keyword",
        "action": "research_run",
        "credit_cost": 30,
        "label": "Keyword Research — DataForSEO Live",
    },
    {
        "module": "keyword",
        "action": "research_cache",
        "credit_cost": 5,
        "cache_zero_cost": False,
        "cache_discount_percent": 0,
        "label": "Keyword Research (cache/basic)",
    },
    {
        "module": "keyword",
        "action": "dataforseo_standard",
        "credit_cost": 20,
        "label": "DataForSEO Standard",
    },
    {
        "module": "keyword",
        "action": "dataforseo_live",
        "credit_cost": 30,
        "label": "DataForSEO Live",
    },
    {
        "module": "keyword",
        "action": "volume_batch_100",
        "credit_cost": 35,
        "cache_discount_percent": 85,
        "label": "Volume batch (mỗi 100 từ khóa, 20–50 qua config)",
    },
    {
        "module": "keyword",
        "action": "cluster_sync",
        "credit_cost": 3,
        "label": "Gom cụm (sync)",
    },
    {
        "module": "keyword",
        "action": "cluster_async",
        "credit_cost": 2,
        "label": "Gom cụm async — đơn vị / 50 từ khóa (local embedding)",
    },
    {
        "module": "keyword",
        "action": "cluster_serp_block",
        "credit_cost": 9,
        "label": "Gom cụm — phụ phí SERP / 50 từ khóa (≥70% GM vs DataForSEO)",
    },
    {
        "module": "keyword",
        "action": "cluster_save",
        "credit_cost": 2,
        "label": "Lưu project gom cụm",
    },
    {
        "module": "keyword",
        "action": "import_excel",
        "credit_cost": 1,
        "label": "Import Excel từ khóa",
    },
    # Audit / SEO score — FREE (không trừ credit)
    {
        "module": "audit",
        "action": "technical_quick",
        "credit_cost": 0,
        "label": "Technical Audit nhanh (FREE)",
    },
    {
        "module": "audit",
        "action": "technical_deep",
        "credit_cost": 0,
        "label": "Technical Audit sâu (FREE)",
    },
    {
        "module": "audit",
        "action": "technical_single_url",
        "credit_cost": 0,
        "label": "Audit 1 URL (FREE)",
    },
    {
        "module": "audit",
        "action": "analyze_project",
        "credit_cost": 10,
        "label": "Phân tích dự án",
    },
    {
        "module": "seo_score",
        "action": "url_scoreboard",
        "credit_cost": 0,
        "label": "SEO Score URL (FREE)",
    },
    {
        "module": "seo_score",
        "action": "content_score",
        "credit_cost": 0,
        "label": "SEO Score nội dung (FREE)",
    },
    {
        "module": "seo_score",
        "action": "ai_fix",
        "credit_cost": 2,
        "label": "SEO Score — Sửa bằng AI",
        "description": "Billable by default; set SEO_SCORE_AI_FIX_BILLING_ENABLED=0 to disable",
    },
    {
        "module": "schema",
        "action": "generate",
        "credit_cost": 0,
        "label": "Schema JSON-LD generate (FREE)",
    },
    # Chatbot CSKH vượt quota
    {
        "module": "chatbot_cskh",
        "action": "reply_overage",
        "credit_cost": 2,
        "label": "Chatbot CSKH — reply vượt quota",
    },
    # Lead Map Scanner
    {
        "module": "lead_scanner",
        "action": "basic_scan",
        "credit_cost": 42,
        "cache_discount_percent": 50,
        "cache_zero_cost": False,
        "label": "Lead scan cơ bản (Places)",
    },
    {
        "module": "lead_scanner",
        "action": "place_detail",
        "credit_cost": 22,
        "label": "Lead — lấy SĐT/chi tiết",
    },
    {
        "module": "lead_scanner",
        "action": "geocode",
        "credit_cost": 2,
        "label": "Lead — geocode khu vực",
    },
    {
        "module": "lead_scanner",
        "action": "export",
        "credit_cost": 8,
        "label": "Lead — xuất CSV/XLSX",
    },
    # Chatbot workflow
    {
        "module": "chatbot",
        "action": "internal_links",
        "credit_cost": 3,
        "label": "Chatbot — internal links",
    },
    {
        "module": "chatbot",
        "action": "images_bundle",
        "credit_cost": 52,
        "label": "Chatbot — gói ảnh AI (theo SSOT ảnh)",
    },
    # Rank Tracking / SERP helpers / Google Map AI
    {
        "module": "rank_tracking",
        "action": "check",
        "credit_cost": 3,
        "label": "Rank Tracking — check SERP",
    },
    {
        "module": "keyword",
        "action": "intelligence",
        "credit_cost": 2,
        "label": "Keyword Intelligence",
    },
    {
        "module": "serp",
        "action": "keyword_intelligence",
        "credit_cost": 3,
        "label": "SERP Keyword Intelligence",
    },
    {
        "module": "google_map",
        "action": "ai_generate",
        "credit_cost": 2,
        "label": "Google Map SEO — AI generate",
    },
    {
        "module": "wordpress",
        "action": "publish",
        "credit_cost": 3,
        "label": "WordPress — đăng bài / plugin publish",
    },
    {
        "module": "index",
        "action": "submit_google",
        "credit_cost": 2,
        "label": "Submit Index — Google Indexing (mỗi lô 10 URL)",
    },
    {
        "module": "index",
        "action": "submit_indexnow",
        "credit_cost": 1,
        "label": "Submit Index — IndexNow (mỗi lô 20 URL)",
    },
    {
        "module": "embedding",
        "action": "openai_batch",
        "credit_cost": 2,
        "label": "Embedding OpenAI fallback (mỗi lô 100 KW)",
    },
    {
        "module": "email",
        "action": "user_notify",
        "credit_cost": 1,
        "label": "Email user-triggered (CSKH/notify vượt soft-cap)",
    },
    {
        "module": "email",
        "action": "compose",
        "credit_cost": 3,
        "label": "Email Marketing — AI Composer (subject + body)",
    },
    {
        "module": "email",
        "action": "rewrite",
        "credit_cost": 2,
        "label": "Email Marketing — AI rewrite / shorter / tone",
    },
    {
        "module": "crawl",
        "action": "job",
        "credit_cost": 2,
        "label": "Crawl worker job (ngoài audit gate)",
    },
    {
        "module": "storage",
        "action": "put",
        "credit_cost": 0,
        "label": "User/local storage put (usage log; 0 credit)",
    },
    {
        "module": "storage",
        "action": "r2_put",
        "credit_cost": 0,
        "label": "R2/S3 put (usage log; 0 credit)",
    },
    {
        "module": "storage",
        "action": "r2_get",
        "credit_cost": 0,
        "label": "R2/S3 get/egress (usage log; 0 credit)",
    },
]

_DEFAULT_MAP: dict[tuple[str, str], dict[str, Any]] = {
    (str(r["module"]), str(r["action"])): r for r in DEFAULT_CREDIT_COSTS
}

# Legacy consume_credits reason → (module, action)
REASON_TO_MODULE_ACTION: dict[str, tuple[str, str]] = {
    "keyword_research_get": ("keyword", "research_cache"),
    "keyword_research_run": ("keyword", "research_run"),
    "keyword_research_async": ("keyword", "research_run"),
    "keyword_suggest": ("keyword", "research_cache"),
    "volume_batch": ("keyword", "volume_batch_100"),
    "cluster_sync": ("keyword", "cluster_sync"),
    "cluster_save": ("keyword", "cluster_save"),
    "keyword_cluster_sync": ("keyword", "cluster_sync"),
    "keyword_cluster_async": ("keyword", "cluster_async"),
    "import_excel": ("keyword", "import_excel"),
    "content_ai_article": ("content_ai", "article_short"),
    "content_ai_brief_suggest": ("content_ai", "brief_suggest"),
    "cau_modal_rewrite_content": ("cau", "modal_rewrite"),
    "cau_modal_append_headings": ("cau", "modal_append"),
    "cau_seo_ai_fix": ("cau", "seo_ai_fix"),
    "technical_analyze": ("audit", "technical_deep"),
    "technical_quick_audit": ("audit", "technical_quick"),
    "technical_deep_audit": ("audit", "technical_deep"),
    "technical_single_url": ("audit", "technical_single_url"),
    "analyze_project": ("audit", "analyze_project"),
    "url_seo_scoreboard": ("seo_score", "url_scoreboard"),
    "content_seo_score": ("seo_score", "content_score"),
    "schema_generate": ("schema", "generate"),
    "lead_map_basic_scan": ("lead_scanner", "basic_scan"),
    "lead_map_place_detail": ("lead_scanner", "place_detail"),
    "lead_map_export": ("lead_scanner", "export"),
    "rank_tracking_check": ("rank_tracking", "check"),
    "keyword_intelligence": ("keyword", "intelligence"),
    "serp_keyword_intelligence": ("serp", "keyword_intelligence"),
    "google_map_ai_generate": ("google_map", "ai_generate"),
    "chatbot_workflow_research": ("keyword", "research_run"),
    "chatbot_workflow_cluster": ("keyword", "cluster_sync"),
    "chatbot_workflow_content_ai": ("content_ai", "article_short"),
    "chatbot_workflow_internal_links": ("chatbot", "internal_links"),
    "chatbot_workflow_images": ("chatbot", "images_bundle"),
    "chatbot_quick_write_content_ai": ("content_ai", "article_short"),
    "chatbot_quick_write_images_google": ("content_ai", "google_image"),
    "chatbot_quick_write_images_ai": ("content_ai", "ai_image"),
    "chatbot_keyword_research": ("keyword", "research_run"),
    "chatbot_cskh_overage": ("chatbot_cskh", "reply_overage"),
    "wp_publish": ("wordpress", "publish"),
    "index_control_submit": ("index", "submit_google"),
    "indexnow_submit": ("index", "submit_indexnow"),
    "embedding_openai": ("embedding", "openai_batch"),
    "email_user_notify": ("email", "user_notify"),
    "email_compose": ("email", "compose"),
    "email_rewrite": ("email", "rewrite"),
    "crawl_job": ("crawl", "job"),
    "storage_put": ("storage", "put"),
    "r2_put": ("storage", "r2_put"),
    "r2_get": ("storage", "r2_get"),
}


# Bumped when DEFAULT_CREDIT_COSTS for locked keys must overwrite DB rows.
CREDIT_SSOT_REVISION = 7

SSOT_LOCK_KEYS: frozenset[tuple[str, str]] = frozenset(
    {
        ("content_ai", "ai_image"),
        ("content_ai", "addon_research"),
        ("lead_scanner", "basic_scan"),
        ("lead_scanner", "place_detail"),
        ("audit", "technical_quick"),
        ("audit", "technical_deep"),
        ("audit", "technical_single_url"),
        ("seo_score", "url_scoreboard"),
        ("seo_score", "content_score"),
        ("schema", "generate"),
        ("chatbot", "images_bundle"),
        ("keyword", "cluster_async"),
        ("keyword", "cluster_serp_block"),
        ("wordpress", "publish"),
        ("index", "submit_google"),
        ("index", "submit_indexnow"),
        ("embedding", "openai_batch"),
        ("email", "user_notify"),
        ("crawl", "job"),
        ("storage", "put"),
        ("storage", "r2_put"),
        ("storage", "r2_get"),
    }
)


def invalidate_credit_cost_cache() -> None:
    global _CONFIG_CACHE
    with _CACHE_LOCK:
        _CONFIG_CACHE = None


def _env_override_key(module: str, action: str) -> str:
    return f"CREDIT_COST_{module}_{action}".upper()


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


def _load_db_configs(db: Session | None) -> dict[str, dict[str, Any]]:
    if db is None:
        return {}
    try:
        from app.models.credit_cost_config import CreditCostConfig

        rows = db.query(CreditCostConfig).filter(CreditCostConfig.is_active.is_(True)).all()
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = f"{row.module}:{row.action}"
            out[key] = {
                "module": row.module,
                "action": row.action,
                "credit_cost": int(row.credit_cost or 0),
                "cache_discount_percent": int(row.cache_discount_percent or 0),
                "cache_zero_cost": bool(row.cache_zero_cost),
                "label": row.label,
                "description": row.description,
            }
        return out
    except Exception:
        return {}


def _get_config_entry(module: str, action: str, db: Session | None = None) -> dict[str, Any]:
    mod = str(module or "").strip().lower()
    act = str(action or "").strip().lower()
    key = f"{mod}:{act}"

    db_row: dict[str, Any] | None = None
    if db is not None:
        db_row = _load_db_configs(db).get(key)
    else:
        global _CONFIG_CACHE
        with _CACHE_LOCK:
            if _CONFIG_CACHE is None:
                _CONFIG_CACHE = {}
            db_row = _CONFIG_CACHE.get(key)

    default_row = _DEFAULT_MAP.get((mod, act), {})

    base_cost = int(default_row.get("credit_cost", 0))
    cache_discount = int(default_row.get("cache_discount_percent", 80))
    cache_zero = bool(default_row.get("cache_zero_cost", False))
    label = default_row.get("label")
    description = default_row.get("description")

    if db_row:
        base_cost = int(db_row.get("credit_cost", base_cost))
        cache_discount = int(db_row.get("cache_discount_percent", cache_discount))
        cache_zero = bool(db_row.get("cache_zero_cost", cache_zero))
        label = db_row.get("label") or label
        description = db_row.get("description") or description

    env_key = _env_override_key(mod, act)
    if os.getenv(env_key) is not None:
        base_cost = max(0, _int_env(env_key, base_cost))

    return {
        "module": mod,
        "action": act,
        "credit_cost": max(0, base_cost),
        "cache_discount_percent": max(0, min(100, cache_discount)),
        "cache_zero_cost": cache_zero,
        "label": label,
        "description": description,
    }


def apply_cache_discount(
    base_cost: int,
    *,
    from_cache: bool,
    cache_discount_percent: int = 80,
    cache_zero_cost: bool = False,
) -> int:
    if not from_cache or base_cost <= 0:
        return max(0, int(base_cost))
    if cache_zero_cost:
        return 0
    pct = max(0, min(100, int(cache_discount_percent)))
    # pct = phần được giảm (80 → chỉ trả 20%)
    pay_ratio = max(0, 100 - pct) / 100.0
    return max(0, int(round(base_cost * pay_ratio)))


def content_ai_action_for_word_count(word_count: int | None) -> str:
    w = max(0, int(word_count or 1000))
    if w <= 1100:
        return "article_short"
    if w <= 1750:
        return "article_medium"
    return "article_long"


def resolve_credit_cost(
    module: str,
    action: str,
    *,
    db: Session | None = None,
    from_cache: bool = False,
    quantity: int = 1,
) -> int:
    """Trả số credit cần trừ (đã áp cache discount nếu có)."""
    cfg = _get_config_entry(module, action, db=db)
    base = int(cfg["credit_cost"]) * max(1, int(quantity))
    return apply_cache_discount(
        base,
        from_cache=from_cache,
        cache_discount_percent=int(cfg["cache_discount_percent"]),
        cache_zero_cost=bool(cfg["cache_zero_cost"]),
    )


def cluster_credit_cost(
    keyword_count: int,
    *,
    async_job: bool = False,
    fetch_serp: bool = False,
    db: Session | None = None,
) -> int:
    """Credit theo số keyword (block 50). Local embedding nằm trong unit; SERP cộng thêm."""
    cap = max(1, _int_env("KEYWORD_CLUSTER_MAX_INPUT", 500))
    n = max(1, min(int(keyword_count or 0), cap))
    unit_action = "cluster_async" if async_job else "cluster_sync"
    unit = resolve_credit_cost("keyword", unit_action, db=db)
    blocks = max(1, (n + 49) // 50)
    cost = int(unit) * blocks
    if fetch_serp:
        cost += resolve_credit_cost("keyword", "cluster_serp_block", db=db) * blocks
    return max(1, cost)


def index_submit_credit_cost(url_count: int, *, provider: str = "google", db: Session | None = None) -> int:
    n = max(1, int(url_count or 1))
    if str(provider or "").strip().lower() == "indexnow":
        unit = resolve_credit_cost("index", "submit_indexnow", db=db)
        blocks = max(1, (n + 19) // 20)
        return unit * blocks
    unit = resolve_credit_cost("index", "submit_google", db=db)
    blocks = max(1, (n + 9) // 10)
    return unit * blocks


def resolve_credit_cost_for_reason(
    reason: str,
    *,
    db: Session | None = None,
    from_cache: bool = False,
    quantity: int = 1,
    word_count: int | None = None,
) -> tuple[str, str, int]:
    """Map legacy reason → module/action + cost."""
    r = str(reason or "").strip().lower()
    mod, act = REASON_TO_MODULE_ACTION.get(r, ("legacy", r[:64] or "unknown"))
    if mod == "content_ai" and act == "article_short" and word_count is not None:
        act = content_ai_action_for_word_count(word_count)
    cost = resolve_credit_cost(mod, act, db=db, from_cache=from_cache, quantity=quantity)
    return mod, act, cost


def list_credit_cost_catalog(*, db: Session | None = None) -> list[dict[str, Any]]:
    invalidate_credit_cost_cache()
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in DEFAULT_CREDIT_COSTS:
        mod, act = str(row["module"]), str(row["action"])
        seen.add((mod, act))
        cfg = _get_config_entry(mod, act, db=db)
        items.append({**cfg, "is_default": True})
    if db is not None:
        try:
            from app.models.credit_cost_config import CreditCostConfig

            for row in db.query(CreditCostConfig).order_by(CreditCostConfig.module, CreditCostConfig.action).all():
                key = (row.module, row.action)
                if key in seen:
                    continue
                seen.add(key)
                items.append(_get_config_entry(row.module, row.action, db=db))
        except Exception:
            pass
    return items


def update_credit_cost_config(
    db: Session,
    *,
    module: str,
    action: str,
    credit_cost: int | None = None,
    cache_discount_percent: int | None = None,
    cache_zero_cost: bool | None = None,
    label: str | None = None,
    description: str | None = None,
    is_active: bool | None = None,
) -> dict[str, Any]:
    from app.models.credit_cost_config import CreditCostConfig

    mod = str(module or "").strip().lower()
    act = str(action or "").strip().lower()
    if not mod or not act:
        raise ValueError("module và action là bắt buộc")

    row = (
        db.query(CreditCostConfig)
        .filter(CreditCostConfig.module == mod, CreditCostConfig.action == act)
        .one_or_none()
    )
    if row is None:
        default = _DEFAULT_MAP.get((mod, act), {})
        row = CreditCostConfig(
            module=mod,
            action=act,
            credit_cost=int(default.get("credit_cost", 0)),
            cache_discount_percent=int(default.get("cache_discount_percent", 80)),
            cache_zero_cost=bool(default.get("cache_zero_cost", False)),
            label=str(default.get("label") or "")[:200] or None,
            description=str(default.get("description") or "")[:2000] or None,
            is_active=True,
        )
        db.add(row)

    if credit_cost is not None:
        row.credit_cost = max(0, int(credit_cost))
    if cache_discount_percent is not None:
        row.cache_discount_percent = max(0, min(100, int(cache_discount_percent)))
    if cache_zero_cost is not None:
        row.cache_zero_cost = bool(cache_zero_cost)
    if label is not None:
        row.label = str(label).strip()[:200] or None
    if description is not None:
        row.description = str(description).strip()[:2000] or None
    if is_active is not None:
        row.is_active = bool(is_active)

    db.flush()
    invalidate_credit_cost_cache()
    return _get_config_entry(mod, act, db=db)


def new_request_id() -> str:
    return uuid.uuid4().hex[:32]


def volume_batch_charge_from_registry(
    keyword_count: int,
    *,
    db: Session | None = None,
    from_cache: bool = False,
) -> int:
    n = max(0, int(keyword_count))
    if n <= 0:
        return 0
    blocks = (n + 99) // 100
    per_block = resolve_credit_cost("keyword", "volume_batch_100", db=db, from_cache=from_cache)
    cap = _int_env("CREDIT_VOLUME_BATCH_MAX_CHARGE", 150)
    total = blocks * per_block
    if cap > 0:
        return min(total, cap)
    return total
