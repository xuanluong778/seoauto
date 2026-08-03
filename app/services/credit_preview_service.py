"""Build credit/quota preview for confirm popup — no external API calls."""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy.orm import Session

from app.models.user import User
from app.services import usage_tracking_service
from app.services.credit_cost_registry import (
    content_ai_action_for_word_count,
    resolve_credit_cost,
)
from app.services.credits import (
    credits_enforced,
    get_available_balance,
    quote_lead_basic_scan,
    quote_lead_detail,
)
from app.services.rbac import is_admin
from app.services.plan_quota_registry import FEATURE_KEY_LABELS_VI, FEATURE_KEYS, FEATURE_LABELS_VI

HIGH_COST_WARNING_DEFAULT = 40

# (module, action) → plan quota key
_ACTION_QUOTA_KEY: dict[tuple[str, str], str] = {
    ("content_ai", "article_short"): "ai_articles",
    ("content_ai", "article_medium"): "ai_articles",
    ("content_ai", "article_long"): "ai_articles",
    ("content_ai", "brief_suggest"): "ai_articles",
    ("content_ai", "ai_image"): "ai_articles",
    ("cau", "seo_ai_fix"): "ai_articles",
    ("cau", "modal_rewrite"): "ai_articles",
    ("cau", "modal_append"): "ai_articles",
    ("keyword", "research_run"): "keyword_research",
    ("keyword", "research_cache"): "keyword_research",
    ("keyword", "volume_batch_100"): "keyword_research",
    ("keyword", "cluster_sync"): "keyword_research",
    ("keyword", "cluster_async"): "keyword_research",
    ("keyword", "cluster_save"): "keyword_research",
    ("keyword", "import_excel"): "keyword_research",
    ("audit", "technical_deep"): "technical_audit",
    ("audit", "technical_quick"): "technical_audit",
    ("audit", "technical_single_url"): "technical_audit",
    ("seo_score", "url_scoreboard"): "seo_score",
    ("seo_score", "content_score"): "seo_score",
    ("seo_score", "ai_fix"): "seo_score",
    ("lead_scanner", "basic_scan"): "lead_scan",
    ("lead_scanner", "place_detail"): "lead_detail",
    ("lead_scanner", "export"): "lead_scan",
    ("chatbot_cskh", "reply_overage"): "chatbot_reply",
    ("content_ai", "google_image"): "ai_articles",
}

_ACTION_LABELS: dict[tuple[str, str], str] = {
    ("content_ai", "article_short"): "Content AI — bài ngắn",
    ("content_ai", "article_medium"): "Content AI — bài trung bình",
    ("content_ai", "article_long"): "Content AI — bài dài",
    ("content_ai", "brief_suggest"): "Content AI — gợi ý title/meta/outline",
    ("content_ai", "google_image"): "Ảnh Google/CSE",
    ("content_ai", "ai_image"): "Ảnh AI (OpenAI)",
    ("cau", "seo_ai_fix"): "Auto Update — Sửa SEO AI",
    ("cau", "modal_rewrite"): "Auto Update — Viết lại content",
    ("cau", "modal_append"): "Auto Update — Thêm heading",
    ("keyword", "research_run"): "Keyword Research",
    ("keyword", "research_cache"): "Keyword Research (cache)",
    ("keyword", "volume_batch_100"): "Tra volume keyword (batch)",
    ("keyword", "cluster_sync"): "Gom cụm keyword",
    ("keyword", "cluster_async"): "Gom cụm keyword (async)",
    ("keyword", "cluster_save"): "Lưu cụm keyword",
    ("keyword", "import_excel"): "Import keyword Excel",
    ("audit", "technical_deep"): "Technical Audit — quét sâu",
    ("audit", "technical_quick"): "Technical Audit — quét nhanh",
    ("audit", "technical_single_url"): "Technical Audit — 1 URL",
    ("seo_score", "url_scoreboard"): "SEO Score — URL scoreboard",
    ("seo_score", "content_score"): "SEO Score — content",
    ("lead_scanner", "basic_scan"): "Lead Map Scanner — quét cơ bản",
    ("lead_scanner", "place_detail"): "Lead Map Scanner — chi tiết SĐT",
    ("lead_scanner", "export"): "Lead Map Scanner — export",
    ("chatbot_cskh", "reply_overage"): "Chatbot CSKH — trả lời AI",
}


def high_cost_threshold() -> int:
    try:
        return max(1, int(os.getenv("CREDIT_HIGH_COST_WARNING", str(HIGH_COST_WARNING_DEFAULT))))
    except (TypeError, ValueError):
        return HIGH_COST_WARNING_DEFAULT


def _resolve_action(module: str, action: str, *, word_count: int | None) -> str:
    mod = str(module or "").strip().lower()
    act = str(action or "").strip().lower()
    if mod == "content_ai" and act in ("article_short", "article_medium", "article_long") and word_count is not None:
        return content_ai_action_for_word_count(word_count)
    return act


def _resolve_label(module: str, action: str, override: str | None) -> str:
    if override and str(override).strip():
        return str(override).strip()[:200]
    return _ACTION_LABELS.get((module, action), f"{module}/{action}")


def _quota_key(module: str, action: str, explicit: str | None) -> str | None:
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    return _ACTION_QUOTA_KEY.get((module, action))


def _compute_credit_cost(
    db: Session,
    *,
    module: str,
    action: str,
    quantity: int,
    from_cache: bool,
    word_count: int | None,
    lead_mode: str | None,
    lead_limit: int | None,
) -> tuple[int, dict[str, Any] | None]:
    if module == "lead_scanner" and action == "basic_scan" and lead_limit:
        quote = quote_lead_basic_scan(
            mode=str(lead_mode or "keyword"),
            limit=int(lead_limit),
            from_cache=from_cache,
            db=db,
        )
        return int(quote.get("credit_required") or 0), quote
    if module == "lead_scanner" and action == "place_detail":
        quote = quote_lead_detail(int(quantity), db=db)
        return int(quote.get("credit_required") or 0), quote

    act = _resolve_action(module, action, word_count=word_count)
    cost = resolve_credit_cost(
        module,
        act,
        db=db,
        from_cache=from_cache,
        quantity=quantity,
    )
    return int(cost), None


def build_credit_preview(
    db: Session,
    user: User,
    *,
    module: str,
    action: str,
    quantity: int = 1,
    from_cache: bool = False,
    quota_key: str | None = None,
    word_count: int | None = None,
    label: str | None = None,
    lead_mode: str | None = None,
    lead_limit: int | None = None,
) -> dict[str, Any]:
    mod = str(module or "").strip().lower()
    act = _resolve_action(mod, str(action or "").strip().lower(), word_count=word_count)
    enabled = credits_enforced()
    admin = is_admin(user)

    credit_cost, breakdown = _compute_credit_cost(
        db,
        module=mod,
        action=act,
        quantity=quantity,
        from_cache=from_cache,
        word_count=word_count,
        lead_mode=lead_mode,
        lead_limit=lead_limit,
    )
    balance = int(get_available_balance(db, user.id)) if enabled else 0
    sufficient = (not enabled) or admin or credit_cost <= 0 or balance >= credit_cost

    qkey = _quota_key(mod, act, quota_key)
    quota_remaining: int | None = None
    quota_limit: int | None = None
    quota_exceeded = False
    quota_label: str | None = None
    feature_key: str | None = None

    if qkey and not admin:
        feature_key = FEATURE_KEYS.get(qkey, qkey)
        quota_label = FEATURE_LABELS_VI.get(qkey) or FEATURE_KEY_LABELS_VI.get(feature_key, qkey)
        remaining = usage_tracking_service.get_quota_remaining(db, user.id, feature_key)
        if remaining is not None:
            quota_remaining = int(remaining)
            if quota_remaining < max(1, int(quantity)):
                quota_exceeded = True
        from app.services.cau_ai_fix_entitlement import resolve_cau_ai_plan_slug
        from app.services.plan_quota_registry import monthly_quota

        plan_slug = resolve_cau_ai_plan_slug(db, user) or "free_trial_5d"
        quota_limit = monthly_quota(plan_slug, qkey)

    if from_cache or (breakdown and breakdown.get("from_cache")):
        data_source = "cache"
        data_source_label = "Dữ liệu từ cache — không gọi API bên ngoài (hoặc 0 credit)"
    else:
        data_source = "api"
        data_source_label = "Sẽ gọi API thật sau khi bạn xác nhận"

    threshold = high_cost_threshold()
    high_cost = enabled and credit_cost >= threshold and not from_cache

    can_proceed = sufficient and not quota_exceeded

    return {
        "credits_enabled": enabled,
        "module": mod,
        "action": act,
        "label": _resolve_label(mod, act, label),
        "credit_cost": credit_cost,
        "credit_balance": balance,
        "credit_balance_after": max(0, balance - credit_cost) if enabled else balance,
        "sufficient_credits": sufficient,
        "quota_key": qkey,
        "quota_label": quota_label,
        "quota_remaining": quota_remaining,
        "quota_limit": quota_limit,
        "quota_exceeded": quota_exceeded,
        "data_source": data_source,
        "data_source_label": data_source_label,
        "high_cost_warning": high_cost,
        "high_cost_threshold": threshold,
        "can_proceed": can_proceed,
        "breakdown": breakdown,
    }


def preview_from_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize client-supplied preview (e.g. lead quote) for confirm UI."""
    return {
        "credits_enabled": bool(data.get("credits_enabled", True)),
        "module": str(data.get("module") or ""),
        "action": str(data.get("action") or ""),
        "label": str(data.get("label") or "Tác vụ tốn phí"),
        "credit_cost": int(data.get("credit_cost") or data.get("credit_required") or 0),
        "credit_balance": int(data.get("credit_balance") or 0),
        "sufficient_credits": bool(data.get("sufficient_credits", True)),
        "quota_key": data.get("quota_key"),
        "quota_label": data.get("quota_label"),
        "quota_remaining": data.get("quota_remaining"),
        "quota_limit": data.get("quota_limit"),
        "quota_exceeded": bool(data.get("quota_exceeded")),
        "data_source": str(data.get("data_source") or ("cache" if data.get("from_cache") else "api")),
        "data_source_label": str(
            data.get("data_source_label")
            or ("Dữ liệu từ cache" if data.get("from_cache") else "Sẽ gọi API thật sau khi xác nhận")
        ),
        "high_cost_warning": bool(data.get("high_cost_warning")),
        "high_cost_threshold": int(data.get("high_cost_threshold") or high_cost_threshold()),
        "can_proceed": bool(data.get("can_proceed", True)),
        "breakdown": data.get("breakdown"),
    }
