"""SEO Helper plugin entitlement — reads existing Subscription / Billing only.

Does not create billing, does not consume credits. Plan limits and features come from
Plan + UsageLimit (catalog) and plan_quota_registry — WordPress plugin must not hard-code tiers.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User
from app.services import plan_service, subscription_service
from app.services.plan_quota_registry import (
    PLAN_FEATURES,
    feature_key_for,
    monthly_quota,
)
from app.services.rbac import is_admin

SITE_FEATURE_KEY = "wordpress_site"
SITE_QUOTA_KEY = "projects"

# Capabilities the WP plugin may toggle when SaaS allows access (not plan slugs).
# content_ops is intentionally NOT listed here — opt-in only (default false).
SEO_HELPER_CAPABILITIES: tuple[str, ...] = (
    "seo_helper",
    "open_graph",
    "schema",
    "yoast_sync",
    "rankmath_sync",
    "seo_audit",
)

# Must be enabled via PLAN_FEATURES[slug]=True, UsageLimit limit_value != 0,
# or PLUGIN_CONTENT_OPS_CANARY_USER_IDS (comma-separated user ids).
# publish_guard / ai_seo_assistant are Phase 2 — explicit opt-in only (default off).
SEO_HELPER_OPT_IN_FEATURES: frozenset[str] = frozenset(
    {"content_ops", "publish_guard", "ai_seo_assistant"}
)


def content_ops_canary_user_ids() -> frozenset[int]:
    """Explicit canary allowlist — default empty (content_ops stays off)."""
    raw = os.getenv("PLUGIN_CONTENT_OPS_CANARY_USER_IDS", "").strip()
    if not raw:
        return frozenset()
    out: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return frozenset(out)


def publish_guard_canary_user_ids() -> frozenset[int]:
    """Explicit canary allowlist — default empty (publish_guard stays off)."""
    raw = os.getenv("PLUGIN_PUBLISH_GUARD_CANARY_USER_IDS", "").strip()
    if not raw:
        return frozenset()
    out: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return frozenset(out)


def ai_seo_canary_user_ids() -> frozenset[int]:
    """Explicit canary allowlist — default empty (ai_seo_assistant stays off)."""
    raw = os.getenv("PLUGIN_AI_SEO_CANARY_USER_IDS", "").strip()
    if not raw:
        return frozenset()
    out: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return frozenset(out)

CANCELED_STATUSES = frozenset({"canceled", "cancelled"})
ACTIVE_STATUSES = subscription_service.ACTIVE_STATUSES  # active | trialing


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def grace_days() -> int:
    raw = os.getenv("PLUGIN_ENTITLEMENT_GRACE_DAYS", "3").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 3


def is_saas_enforcement_enabled() -> bool:
    return os.getenv("SAAS_ENFORCEMENT", "0").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class PluginEntitlement:
    allowed: bool
    reason: str
    plan_code: str | None
    subscription_status: str | None
    expires_at: datetime | None
    grace_until: datetime | None
    max_sites: int
    enabled_features: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("expires_at", "grace_until"):
            val = data.get(key)
            if isinstance(val, datetime):
                data[key] = val.isoformat()
        return data


class PluginEntitlementService:
    """Resolve SEO Helper access from current Subscription + Plan usage_limits."""

    site_feature_key = SITE_FEATURE_KEY

    def check(
        self,
        db: Session,
        user: User | None,
        *,
        current_site_count: int = 0,
        now: datetime | None = None,
    ) -> PluginEntitlement:
        """Return entitlement snapshot. Never deducts credits."""
        now = _aware(now) or _utc_now()
        sites = max(0, int(current_site_count or 0))

        if user is None:
            return PluginEntitlement(
                allowed=False,
                reason="not_authenticated",
                plan_code=None,
                subscription_status=None,
                expires_at=None,
                grace_until=None,
                max_sites=0,
                enabled_features=[],
            )

        if is_admin(user):
            features = self._with_content_ops_canary(user, self._admin_features())
            return self._maybe_site_limit(
                PluginEntitlement(
                    allowed=True,
                    reason="admin",
                    plan_code="admin",
                    subscription_status="active",
                    expires_at=None,
                    grace_until=None,
                    max_sites=-1,
                    enabled_features=features,
                ),
                sites,
            )

        if not is_saas_enforcement_enabled():
            # Soft-open when enforcement off — still expose plan snapshot if present.
            sub, plan = self._latest_sub_and_plan(db, user.id)
            plan_code = plan.slug if plan else None
            max_sites = self._max_sites_for_plan(db, plan)
            features = self._with_content_ops_canary(
                user,
                self._enabled_features(db, plan) if plan else list(SEO_HELPER_CAPABILITIES),
            )
            status = self._public_status(sub, now=now) if sub else None
            expires_at = _aware(sub.current_period_end) if sub else None
            grace_until = self._grace_until(expires_at) if expires_at else None
            return self._maybe_site_limit(
                PluginEntitlement(
                    allowed=True,
                    reason="legacy_enforcement_off",
                    plan_code=plan_code,
                    subscription_status=status,
                    expires_at=expires_at,
                    grace_until=grace_until,
                    max_sites=max_sites,
                    enabled_features=features,
                ),
                sites,
            )

        sub, plan = self._latest_sub_and_plan(db, user.id)
        if sub is None or plan is None:
            return PluginEntitlement(
                allowed=False,
                reason="no_subscription",
                plan_code=None,
                subscription_status=None,
                expires_at=None,
                grace_until=None,
                max_sites=0,
                enabled_features=[],
            )

        plan_code = str(plan.slug or "").strip().lower() or None
        expires_at = _aware(sub.current_period_end)
        grace_until = self._grace_until(expires_at)
        public_status = self._public_status(sub, now=now)
        max_sites = self._max_sites_for_plan(db, plan)
        features = self._with_content_ops_canary(user, self._enabled_features(db, plan))

        access_reason = self._access_reason(sub, now=now, expires_at=expires_at, grace_until=grace_until)
        if access_reason is None:
            return PluginEntitlement(
                allowed=False,
                reason=self._deny_reason(sub, now=now, expires_at=expires_at, grace_until=grace_until),
                plan_code=plan_code,
                subscription_status=public_status,
                expires_at=expires_at,
                grace_until=grace_until,
                max_sites=max_sites,
                enabled_features=[],
            )

        return self._maybe_site_limit(
            PluginEntitlement(
                allowed=True,
                reason=access_reason,
                plan_code=plan_code,
                subscription_status=public_status,
                expires_at=expires_at,
                grace_until=grace_until,
                max_sites=max_sites,
                enabled_features=features,
            ),
            sites,
        )

    def check_dict(
        self,
        db: Session,
        user: User | None,
        *,
        current_site_count: int = 0,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        return self.check(db, user, current_site_count=current_site_count, now=now).to_dict()

    # --- internals ---

    def _latest_sub_and_plan(self, db: Session, user_id: int) -> tuple[Subscription | None, Plan | None]:
        # Prefer currently active subscription; otherwise latest by period end (expired/canceled).
        sub = subscription_service.get_active_subscription(db, user_id)
        if sub is None:
            sub = (
                db.query(Subscription)
                .filter(Subscription.user_id == int(user_id))
                .order_by(Subscription.current_period_end.desc(), Subscription.id.desc())
                .first()
            )
        if sub is None:
            return None, None
        plan = plan_service.get_plan_with_limits(db, sub.plan_id) or plan_service.get_plan_by_id(
            db, sub.plan_id
        )
        return sub, plan

    def _max_sites_for_plan(self, db: Session, plan: Plan | None) -> int:
        if plan is None:
            return 0
        limit_row = plan_service.get_limit_for_feature(db, plan.id, SITE_FEATURE_KEY)
        if limit_row is not None:
            return int(limit_row.limit_value)
        # Fallback to registry (same source used to seed usage_limits).
        return int(monthly_quota(str(plan.slug or ""), SITE_QUOTA_KEY))

    def _enabled_features(self, db: Session, plan: Plan | None) -> list[str]:
        if plan is None:
            return []
        slug = str(plan.slug or "").strip().lower()
        features: set[str] = set(SEO_HELPER_CAPABILITIES)

        for key, val in PLAN_FEATURES.get(slug, {}).items():
            if val is True:
                features.add(str(key))
            elif val is False and str(key) in features:
                # Explicit plan flag can disable a capability (e.g. seo_audit=False).
                features.discard(str(key))

        limits = plan_service.get_limits_for_plan(db, plan.id)
        for row in limits:
            try:
                lim = int(row.limit_value)
            except (TypeError, ValueError):
                continue
            key = str(row.feature_key)
            if lim == 0:
                # Quota 0 disables the feature even if present in base capabilities.
                features.discard(key)
                continue
            # lim == -1 means unlimited; still enable the feature key
            features.add(key)

        # Opt-in features (content_ops): not in SEO_HELPER_CAPABILITIES.
        # Present only when PLAN_FEATURES[slug]=True or UsageLimit limit_value != 0 above.
        for key in SEO_HELPER_OPT_IN_FEATURES:
            if PLAN_FEATURES.get(slug, {}).get(key) is False:
                features.discard(key)

        # Ensure site/publish keys present when quota > 0
        site_cap = self._max_sites_for_plan(db, plan)
        if site_cap != 0:
            features.add(SITE_FEATURE_KEY)
            features.add(feature_key_for(SITE_QUOTA_KEY))

        return sorted(features)

    def _with_content_ops_canary(self, user: User, features: list[str]) -> list[str]:
        out = set(features)
        if "content_ops" not in out and int(getattr(user, "id", 0) or 0) in content_ops_canary_user_ids():
            out.add("content_ops")
        if "publish_guard" not in out and int(getattr(user, "id", 0) or 0) in publish_guard_canary_user_ids():
            out.add("publish_guard")
        if "ai_seo_assistant" not in out and int(getattr(user, "id", 0) or 0) in ai_seo_canary_user_ids():
            out.add("ai_seo_assistant")
        return sorted(out)

    def _admin_features(self) -> list[str]:
        # Admins get base SEO Helper capabilities; opt-in features stay off unless
        # explicitly granted via plan/usage limits on a real subscription path.
        features = set(SEO_HELPER_CAPABILITIES)
        for feats in PLAN_FEATURES.values():
            for key, val in feats.items():
                if val is True and key not in SEO_HELPER_OPT_IN_FEATURES:
                    features.add(str(key))
        features.add(SITE_FEATURE_KEY)
        features.add("wp_publish")
        return sorted(features)

    def _grace_until(self, expires_at: datetime | None) -> datetime | None:
        end = _aware(expires_at)
        if end is None:
            return None
        days = grace_days()
        if days <= 0:
            return end
        return end + timedelta(days=days)

    def _public_status(self, sub: Subscription, *, now: datetime) -> str:
        raw = str(sub.status or "").strip().lower()
        if raw in CANCELED_STATUSES:
            return "canceled"
        if bool(sub.cancel_at_period_end) or sub.cancelled_at is not None:
            # Still may be within paid period — surface as canceled for plugin clients.
            if raw in ACTIVE_STATUSES:
                return "canceled"
            return "canceled"
        expires_at = _aware(sub.current_period_end)
        grace_until = self._grace_until(expires_at)
        if raw in ACTIVE_STATUSES and expires_at and expires_at > now:
            return raw
        if raw == "expired" or (expires_at is not None and expires_at <= now):
            if grace_until and now <= grace_until and raw in ACTIVE_STATUSES | {"expired"} | CANCELED_STATUSES:
                # Keep reporting expired when past period_end
                return "expired" if expires_at <= now else raw
            return "expired" if expires_at and expires_at <= now else raw
        return raw or "unknown"

    def _access_reason(
        self,
        sub: Subscription,
        *,
        now: datetime,
        expires_at: datetime | None,
        grace_until: datetime | None,
    ) -> str | None:
        """Return reason string when access is granted; None when denied."""
        status = str(sub.status or "").strip().lower()
        ended = _aware(sub.ended_at)
        if ended is not None and ended <= now and status not in ACTIVE_STATUSES | CANCELED_STATUSES:
            # Hard-ended outside normal cancel/expire flow
            if grace_until and now <= grace_until:
                return "grace"
            return None

        in_period = expires_at is not None and now < expires_at
        in_grace = (
            expires_at is not None
            and grace_until is not None
            and expires_at <= now <= grace_until
        )

        if status in ACTIVE_STATUSES and in_period:
            if bool(sub.cancel_at_period_end) or sub.cancelled_at is not None:
                return "cancel_at_period_end"
            return "active"

        if status in CANCELED_STATUSES and in_period:
            return "cancel_at_period_end"

        if status in CANCELED_STATUSES and in_grace:
            return "grace"

        if status == "expired" and in_grace:
            return "grace"

        # Period lapsed while status still "active" (clock skew / not yet expired row)
        if status in ACTIVE_STATUSES and in_grace:
            return "grace"

        if status in ACTIVE_STATUSES and in_period:
            return "active"

        return None

    def _deny_reason(
        self,
        sub: Subscription,
        *,
        now: datetime,
        expires_at: datetime | None,
        grace_until: datetime | None,
    ) -> str:
        status = str(sub.status or "").strip().lower()
        if status in CANCELED_STATUSES:
            return "canceled"
        if status == "expired" or (expires_at is not None and expires_at <= now):
            if grace_until is not None and now > grace_until:
                return "expired"
            return "expired"
        return "subscription_inactive"

    def _maybe_site_limit(self, ent: PluginEntitlement, current_site_count: int) -> PluginEntitlement:
        if not ent.allowed:
            return ent
        max_sites = int(ent.max_sites)
        if max_sites < 0:
            return ent  # unlimited
        if current_site_count > max_sites:
            return PluginEntitlement(
                allowed=False,
                reason="site_limit_exceeded",
                plan_code=ent.plan_code,
                subscription_status=ent.subscription_status,
                expires_at=ent.expires_at,
                grace_until=ent.grace_until,
                max_sites=max_sites,
                enabled_features=ent.enabled_features,
            )
        return ent


# Module-level singleton for convenient imports
plugin_entitlement_service = PluginEntitlementService()


def check_plugin_entitlement(
    db: Session,
    user: User | None,
    *,
    current_site_count: int = 0,
    now: datetime | None = None,
) -> PluginEntitlement:
    return plugin_entitlement_service.check(
        db, user, current_site_count=current_site_count, now=now
    )
