"""Kiểm soát chi phí DataForSEO — credit, plan, cache-first, logging."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.dataforseo_usage_log import DataforseoUsageLog
from app.models.user import User
from app.services.cau_ai_fix_entitlement import resolve_cau_ai_plan_slug
from app.services.credit_cost_registry import resolve_credit_cost
from app.services.credits import consume_credits, cost_research_run, credits_enforced, volume_batch_charge
from app.services.plan_quota_registry import plan_feature
from app.services.rbac import is_admin

_LOG = logging.getLogger("dataforseo.billing")

KW_ADVANCED_MESSAGE = (
    "DataForSEO nâng cao (Live API) chỉ có từ gói Pro trở lên. "
    "Gói Basic dùng nghiên cứu cơ bản/cache. Nâng cấp tại /pricing."
)
DATAFORSEO_ERROR_MESSAGE = (
    "DataForSEO tạm thời không khả dụng (hết quota hoặc lỗi kết nối). "
    "Vui lòng thử lại sau hoặc dùng dữ liệu cache."
)


@dataclass
class DataforseoStats:
    api_tasks: int = 0
    cache_hits: int = 0
    keywords_total: int = 0
    keywords_api: int = 0
    dataforseo_calls: int = 0
    google_ads_calls: int = 0

    def merge(self, other: dict[str, Any] | "DataforseoStats | None") -> None:
        if not other:
            return
        if isinstance(other, DataforseoStats):
            self.api_tasks += int(other.api_tasks)
            self.cache_hits += int(other.cache_hits)
            self.keywords_total = max(self.keywords_total, int(other.keywords_total))
            self.keywords_api += int(other.keywords_api)
            self.dataforseo_calls += int(other.dataforseo_calls)
            self.google_ads_calls += int(other.google_ads_calls)
            return
        self.api_tasks += int(other.get("api_tasks") or 0)
        self.cache_hits += int(other.get("cache_hits") or 0)
        self.keywords_total = max(self.keywords_total, int(other.get("keywords_total") or 0))
        self.keywords_api += int(other.get("keywords_api") or 0)
        self.dataforseo_calls += int(other.get("dataforseo_calls") or 0)
        self.google_ads_calls += int(other.get("google_ads_calls") or 0)


def user_may_use_dataforseo_live(db: Session, user: User) -> bool:
    if is_admin(user):
        return True
    slug = resolve_cau_ai_plan_slug(db, user)
    if not slug:
        return False
    return bool(plan_feature(slug, "kw_advanced", False))


def assert_dataforseo_live_allowed(db: Session, user: User) -> str | None:
    if is_admin(user):
        return "admin"
    slug = resolve_cau_ai_plan_slug(db, user)
    if not slug:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "plan_required",
                "message": KW_ADVANCED_MESSAGE,
                "upgrade_url": "/pricing",
            },
        )
    if not plan_feature(slug, "kw_advanced", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "kw_basic_only",
                "message": KW_ADVANCED_MESSAGE,
                "upgrade_url": "/pricing",
            },
        )
    return slug


def cost_dataforseo_live(*, db: Session | None = None) -> int:
    return resolve_credit_cost("keyword", "dataforseo_live", db=db)


def cost_dataforseo_standard(*, db: Session | None = None) -> int:
    return resolve_credit_cost("keyword", "dataforseo_standard", db=db)


def cost_research_cache(*, db: Session | None = None) -> int:
    return cost_research_run(db=db, from_cache=True)


@dataclass
class ResearchBillingPreview:
    credit_cost: int
    api_mode: str
    cache_hit: bool
    allow_live: bool
    k4k_cache_hits: int = 0
    k4k_api_tasks: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "credit_cost": self.credit_cost,
            "api_mode": self.api_mode,
            "cache_hit": self.cache_hit,
            "allow_live": self.allow_live,
            "k4k_cache_hits": self.k4k_cache_hits,
            "k4k_api_tasks": self.k4k_api_tasks,
        }


def preview_research_billing(
    db: Session | None,
    user: User,
    *,
    seeds: list[str],
    country: str | None,
    language: str | None,
) -> ResearchBillingPreview:
    import os

    from app.services.keyword_ads_expand import peek_ads_ideas_cache_status
    from app.services.keyword_dataforseo_expand import peek_k4k_cache_status
    from app.services.volume_providers.google_ads import google_ads_configured

    allow_live = user_may_use_dataforseo_live(db, user) if db is not None else False
    k4k = peek_k4k_cache_status(seeds, country=country, language=language)
    ads = peek_ads_ideas_cache_status(seeds, country=country, language=language)
    seed_list = [str(s).strip() for s in (seeds or []) if str(s).strip()]
    seed_keys = [s.lower() for s in seed_list]

    def _hit_set(peek: dict[str, Any]) -> set[str]:
        if "hit_seeds" in peek:
            return {str(s).strip().lower() for s in (peek.get("hit_seeds") or []) if str(s).strip()}
        if int(peek.get("misses") or 0) == 0 and int(peek.get("hits") or 0) > 0:
            return set(seed_keys)
        return set()

    covered = _hit_set(ads) | _hit_set(k4k)
    union_hits = sum(1 for k in seed_keys if k in covered)
    union_misses = sum(1 for k in seed_keys if k not in covered)
    all_cached = union_misses == 0 and union_hits > 0
    ads_primary = google_ads_configured() and os.getenv("VOLUME_API_ENABLED", "0").lower() in (
        "1",
        "true",
        "yes",
    )

    if is_admin(user):
        return ResearchBillingPreview(
            credit_cost=0,
            api_mode="admin",
            cache_hit=all_cached,
            allow_live=True,
            k4k_cache_hits=union_hits,
            k4k_api_tasks=union_misses,
        )

    if all_cached:
        cost = cost_research_cache(db=db)
        return ResearchBillingPreview(
            credit_cost=cost,
            api_mode="cache",
            cache_hit=True,
            allow_live=allow_live,
            k4k_cache_hits=union_hits,
            k4k_api_tasks=0,
        )

    if not allow_live:
        cost = cost_research_cache(db=db)
        return ResearchBillingPreview(
            credit_cost=cost,
            api_mode="basic",
            cache_hit=False,
            allow_live=False,
            k4k_cache_hits=union_hits,
            k4k_api_tasks=0,
        )

    if ads_primary:
        cost = cost_research_cache(db=db)
        return ResearchBillingPreview(
            credit_cost=cost,
            api_mode="cache",
            cache_hit=False,
            allow_live=True,
            k4k_cache_hits=union_hits,
            k4k_api_tasks=0,
        )

    cost = cost_dataforseo_live(db=db)
    return ResearchBillingPreview(
        credit_cost=cost,
        api_mode="live",
        cache_hit=False,
        allow_live=True,
        k4k_cache_hits=union_hits,
        k4k_api_tasks=union_misses,
    )


@dataclass
class VolumeBatchBillingPreview:
    credit_cost: int
    cache_hits: int
    api_keywords: int
    total_keywords: int
    from_cache: bool
    allow_live: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "credit_cost": self.credit_cost,
            "cache_hits": self.cache_hits,
            "api_keywords": self.api_keywords,
            "total_keywords": self.total_keywords,
            "from_cache": self.from_cache,
            "allow_live": self.allow_live,
        }


def preview_volume_batch_billing(
    db: Session | None,
    user: User,
    *,
    keywords: list[str],
    country: str | None,
    language: str | None,
) -> VolumeBatchBillingPreview:
    from app.services.search_volume import peek_volume_cache_status

    allow_live = user_may_use_dataforseo_live(db, user) if db is not None else False
    peek = peek_volume_cache_status(keywords, country=country, language=language)
    api_kw = int(peek.get("misses") or 0)
    hits = int(peek.get("hits") or 0)
    total = int(peek.get("total") or 0)

    if is_admin(user):
        return VolumeBatchBillingPreview(
            credit_cost=0,
            cache_hits=hits,
            api_keywords=api_kw,
            total_keywords=total,
            from_cache=api_kw == 0,
            allow_live=True,
        )

    if api_kw <= 0:
        cost = volume_batch_charge(total, db=db, from_cache=True) if total > 0 else 0
        return VolumeBatchBillingPreview(
            credit_cost=cost,
            cache_hits=hits,
            api_keywords=0,
            total_keywords=total,
            from_cache=True,
            allow_live=allow_live,
        )

    if not allow_live:
        cost = volume_batch_charge(total, db=db, from_cache=True)
        return VolumeBatchBillingPreview(
            credit_cost=cost,
            cache_hits=hits,
            api_keywords=0,
            total_keywords=total,
            from_cache=True,
            allow_live=False,
        )

    blocks = (api_kw + 99) // 100
    cost = volume_batch_charge(blocks * 100, db=db, from_cache=False)
    return VolumeBatchBillingPreview(
        credit_cost=cost,
        cache_hits=hits,
        api_keywords=api_kw,
        total_keywords=total,
        from_cache=False,
        allow_live=True,
    )


def charge_research_credits(
    db: Session,
    user: User,
    *,
    preview: ResearchBillingPreview,
    stats: DataforseoStats,
    seeds_count: int,
) -> int:
    if is_admin(user) or not credits_enforced():
        return 0

    used_live = int(stats.dataforseo_calls or 0) > 0
    if used_live:
        amount = cost_dataforseo_live(db=db)
        action = "dataforseo_live"
        reason = "keyword_research_run"
        api_mode = "live"
    else:
        amount = cost_research_cache(db=db)
        action = "research_cache"
        reason = "keyword_research_run"
        api_mode = preview.api_mode or "cache"

    if amount <= 0:
        return 0

    note = json.dumps(
        {
            "seeds": seeds_count,
            "api_tasks": stats.api_tasks,
            "cache_hits": stats.cache_hits,
            "mode": api_mode,
        },
        ensure_ascii=False,
    )[:500]

    consume_credits(
        db,
        user_id=int(user.id),
        amount=amount,
        reason=reason,
        note=note,
        module="keyword",
        action=action,
        source="cache" if not used_live else "api",
    )
    return amount


def charge_volume_batch_credits(
    db: Session,
    user: User,
    *,
    preview: VolumeBatchBillingPreview,
    stats: DataforseoStats,
) -> int:
    if is_admin(user) or not credits_enforced():
        return 0

    dfs_n = int(stats.dataforseo_calls or 0)
    if dfs_n > 0:
        amount = volume_batch_charge(
            int(stats.keywords_api or preview.api_keywords or 0) or preview.total_keywords,
            db=db,
            from_cache=False,
        )
        action = "volume_batch_100"
        source = "api"
    else:
        amount = volume_batch_charge(preview.total_keywords, db=db, from_cache=True) if preview.total_keywords else 0
        action = "volume_batch_100"
        source = "cache"

    if amount <= 0:
        return 0

    note = json.dumps(
        {
            "keywords": preview.total_keywords,
            "api_keywords": int(preview.api_keywords or 0),
            "dataforseo_calls": dfs_n,
            "api_tasks": stats.api_tasks,
            "cache_hits": stats.cache_hits,
        },
        ensure_ascii=False,
    )[:500]

    consume_credits(
        db,
        user_id=int(user.id),
        amount=amount,
        reason="volume_batch",
        note=note,
        module="keyword",
        action=action,
        source=source,
    )
    return amount


def maybe_log_dataforseo_usage(
    db: Session,
    *,
    stats: dict[str, Any] | DataforseoStats | None,
    user_id: int | None,
    action: str,
    endpoint: str = "",
    api_mode: str = "cache",
    credit_charged: int = 0,
    cache_hit: int = 0,
    keyword_count: int = 0,
    plan_slug: str | None = None,
    note: str | None = None,
) -> None:
    """Write DFS usage only when DataForSEO was actually called."""
    if isinstance(stats, DataforseoStats):
        dfs_n = int(stats.dataforseo_calls or 0)
        hits = int(stats.cache_hits or cache_hit or 0)
    else:
        dfs_n = int((stats or {}).get("dataforseo_calls") or 0)
        hits = int((stats or {}).get("cache_hits") or cache_hit or 0)
    if dfs_n <= 0:
        return
    log_dataforseo_usage(
        db,
        user_id=user_id,
        action=action,
        endpoint=endpoint,
        api_mode=api_mode if api_mode and api_mode != "cache" else "live",
        tasks_count=dfs_n,
        credit_charged=credit_charged,
        cache_hit=hits,
        api_called=dfs_n,
        keyword_count=keyword_count,
        plan_slug=plan_slug,
        note=note,
    )


def log_dataforseo_usage(
    db: Session,
    *,
    user_id: int | None,
    action: str,
    endpoint: str = "",
    api_mode: str = "cache",
    tasks_count: int = 0,
    credit_charged: int = 0,
    cache_hit: int = 0,
    api_called: int = 0,
    keyword_count: int = 0,
    plan_slug: str | None = None,
    note: str | None = None,
) -> None:
    try:
        row = DataforseoUsageLog(
            user_id=int(user_id) if user_id else None,
            action=str(action or "")[:64],
            endpoint=str(endpoint or "")[:128],
            api_mode=str(api_mode or "cache")[:32],
            tasks_count=max(0, int(tasks_count)),
            credit_charged=max(0, int(credit_charged)),
            cache_hit=max(0, int(cache_hit)),
            api_called=max(0, int(api_called)),
            keyword_count=max(0, int(keyword_count)),
            plan_slug=(plan_slug or "")[:32] or None,
            note=(note or "")[:2000] or None,
        )
        db.add(row)
        db.flush()
    except Exception as exc:
        _LOG.warning("dataforseo_usage_log_failed: %s", exc)


def admin_dataforseo_cost_summary(db: Session) -> dict[str, Any]:
    """Tổng hợp chi phí DataForSEO theo ngày/tháng cho admin."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = day_start.replace(day=1)

    def _agg(since):
        rows = (
            db.query(
                func.coalesce(func.sum(DataforseoUsageLog.credit_charged), 0),
                func.coalesce(func.sum(DataforseoUsageLog.api_called), 0),
                func.coalesce(func.sum(DataforseoUsageLog.cache_hit), 0),
                func.coalesce(func.sum(DataforseoUsageLog.tasks_count), 0),
                func.count(DataforseoUsageLog.id),
            )
            .filter(DataforseoUsageLog.created_at >= since)
            .one()
        )
        credits = int(rows[0] or 0)
        from app.services.saas_economics_service import _estimate_cost_vnd, load_economics_settings

        settings = load_economics_settings(db)
        return {
            "credit_charged": credits,
            "estimated_cost_vnd": _estimate_cost_vnd(credits, "dataforseo", settings),
            "api_calls": int(rows[1] or 0),
            "cache_hits": int(rows[2] or 0),
            "tasks": int(rows[3] or 0),
            "log_rows": int(rows[4] or 0),
        }

    by_action = (
        db.query(
            DataforseoUsageLog.action,
            func.sum(DataforseoUsageLog.credit_charged),
            func.sum(DataforseoUsageLog.api_called),
            func.count(DataforseoUsageLog.id),
        )
        .filter(DataforseoUsageLog.created_at >= month_start)
        .group_by(DataforseoUsageLog.action)
        .all()
    )
    actions = [
        {
            "action": str(a or ""),
            "credit_charged": int(c or 0),
            "api_calls": int(api or 0),
            "count": int(n or 0),
        }
        for a, c, api, n in by_action
    ]

    return {
        "today": _agg(day_start),
        "month": _agg(month_start),
        "by_action_month": actions,
    }


def friendly_http_exception(exc: Exception) -> HTTPException | None:
    msg = str(exc or "").lower()
    if "quota" in msg or "limit" in msg or "402" in msg or "payment" in msg:
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "dataforseo_quota", "message": DATAFORSEO_ERROR_MESSAGE},
        )
    if "timeout" in msg or "connection" in msg or "dataforseo" in msg:
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "dataforseo_error", "message": DATAFORSEO_ERROR_MESSAGE},
        )
    return None
