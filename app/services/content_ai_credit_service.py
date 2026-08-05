"""Content AI variable credit pricing — word tiers + resource addons."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass, field as dc_field
from typing import Any

from sqlalchemy.orm import Session

from app.models.user import User
from app.services.credit_cost_registry import (
    content_ai_action_for_word_count,
    new_request_id,
    resolve_credit_cost,
)
from app.services.credits import (
    commit_reservation,
    consume_credits,
    credits_enforced,
    get_available_balance,
    grant_credits,
    release_reservation,
    reserve_credits,
)
from app.services.rbac import is_admin


@dataclass
class ContentAiBillingFlags:
    include_research: bool = False
    include_outline: bool = False
    include_internal_links: bool = False
    include_rewrite: bool = False
    image_source: str | None = None
    project_id: str | None = None
    article_title: str | None = None
    primary_keyword: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "include_research": bool(self.include_research),
            "include_outline": bool(self.include_outline),
            "include_internal_links": bool(self.include_internal_links),
            "include_rewrite": bool(self.include_rewrite),
            "image_source": (self.image_source or "none").strip().lower() or "none",
            "project_id": (self.project_id or "")[:64] or None,
            "article_title": (self.article_title or "")[:200] or None,
            "primary_keyword": (self.primary_keyword or "")[:200] or None,
        }


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


def byok_billing_mode() -> str:
    return (os.getenv("CONTENT_AI_BYOK_BILLING_MODE", "quota_only") or "quota_only").strip().lower()


def resolve_billing_policy(*, user: User, use_system_llm: bool) -> dict[str, Any]:
    """Mọi user thường dùng API hệ thống — luôn trừ credit khi có phí."""
    if is_admin(user):
        return {"charge_credits": False, "multiplier": 0.0, "mode": "admin"}
    return {"charge_credits": True, "multiplier": 1.0, "mode": "system_api"}


def _image_slots(word_count: int | None, image_source: str | None) -> int:
    src = str(image_source or "none").strip().lower()
    if src not in ("google", "ai", "web"):
        return 0
    from app.services.content_ai_image_rules import image_credit_slots

    return int(image_credit_slots(word_count))


def _addon_lines(
    db: Session | None,
    *,
    flags: ContentAiBillingFlags,
    word_count: int | None,
    field: str,
) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    requested = (field or "content").strip().lower()

    if flags.include_research:
        cost = resolve_credit_cost("content_ai", "addon_research", db=db)
        lines.append(
            {
                "key": "research",
                "module": "content_ai",
                "action": "addon_research",
                "label": "Nghiên cứu từ khóa / SERP",
                "credit_cost": cost,
            }
        )

    if flags.include_outline and requested == "content":
        cost = resolve_credit_cost("content_ai", "addon_outline", db=db)
        lines.append(
            {
                "key": "outline",
                "module": "content_ai",
                "action": "addon_outline",
                "label": "Tạo dàn ý",
                "credit_cost": cost,
            }
        )

    if flags.include_internal_links:
        cost = resolve_credit_cost("content_ai", "addon_internal_link", db=db)
        lines.append(
            {
                "key": "internal_links",
                "module": "content_ai",
                "action": "addon_internal_link",
                "label": "Internal link",
                "credit_cost": cost,
            }
        )

    if flags.include_rewrite:
        cost = resolve_credit_cost("content_ai", "addon_rewrite", db=db)
        lines.append(
            {
                "key": "rewrite",
                "module": "content_ai",
                "action": "addon_rewrite",
                "label": "Viết lại nội dung có sẵn",
                "credit_cost": cost,
            }
        )

    src = str(flags.image_source or "none").strip().lower()
    slots = _image_slots(word_count, src)
    if slots > 0:
        if src == "ai":
            unit = resolve_credit_cost("content_ai", "ai_image", db=db)
            act = "ai_image"
            label = "Ảnh AI"
        else:
            unit = resolve_credit_cost("content_ai", "google_image", db=db)
            act = "google_image"
            label = "Ảnh Google/CSE"
        cost = unit * slots
        lines.append(
            {
                "key": "images",
                "module": "content_ai",
                "action": act,
                "label": f"{label} × {slots}",
                "credit_cost": cost,
                "quantity": slots,
            }
        )

    return lines


def billing_flags_from_request(
    *,
    field: str,
    outline_content: str = "",
    content: str = "",
    billing: dict[str, Any] | ContentAiBillingFlags | None = None,
    project_id: str | None = None,
    title: str = "",
    primary_keyword: str = "",
) -> ContentAiBillingFlags:
    if isinstance(billing, ContentAiBillingFlags):
        return billing
    raw = billing if isinstance(billing, dict) else {}
    requested = (field or "content").strip().lower()
    outline_empty = not str(outline_content or "").strip()
    import re

    plain = re.sub(r"<[^>]+>", " ", str(content or ""))
    has_content = len(plain.strip()) >= 80
    return ContentAiBillingFlags(
        include_research=bool(raw.get("include_research")),
        include_outline=bool(raw.get("include_outline")) if "include_outline" in raw else (outline_empty and requested == "content"),
        include_internal_links=bool(raw.get("include_internal_links")),
        include_rewrite=bool(raw.get("include_rewrite")) if "include_rewrite" in raw else (has_content and requested == "content"),
        image_source=str(raw.get("image_source") or "none").strip().lower() or None,
        project_id=str(raw.get("project_id") or project_id or "")[:64] or None,
        article_title=str(raw.get("article_title") or title or "")[:200] or None,
        primary_keyword=str(raw.get("primary_keyword") or primary_keyword or "")[:200] or None,
    )


def quote_content_ai_write(
    db: Session | None,
    user: User,
    *,
    field: str = "content",
    word_count: int | None = None,
    flags: ContentAiBillingFlags | None = None,
    use_system_llm: bool = True,
    from_cache: bool = False,
) -> dict[str, Any]:
    """Ước tính credit cho một lần viết/gợi ý Content AI."""
    requested = (field or "content").strip().lower()
    flags = flags or ContentAiBillingFlags()
    wc = max(0, int(word_count or 1000))
    policy = resolve_billing_policy(user=user, use_system_llm=use_system_llm)

    if requested == "content":
        tier_action = content_ai_action_for_word_count(wc)
        tier_labels = {
            "article_short": "Viết bài 700–1000 từ",
            "article_medium": "Viết bài ~1500 từ",
            "article_long": "Viết bài ~2000 từ",
        }
        base_cost = resolve_credit_cost("content_ai", tier_action, db=db, from_cache=from_cache)
        lines: list[dict[str, Any]] = [
            {
                "key": "base",
                "module": "content_ai",
                "action": tier_action,
                "label": tier_labels.get(tier_action, "Viết bài"),
                "credit_cost": base_cost,
                "word_count": wc,
            }
        ]
        lines.extend(_addon_lines(db, flags=flags, word_count=wc, field=requested))
        subtotal = sum(int(x.get("credit_cost") or 0) for x in lines)
        mult = float(policy.get("multiplier") or 0.0) if policy.get("charge_credits") else 0.0
        total = max(0, int(round(subtotal * mult))) if mult > 0 else 0
        charge = bool(policy.get("charge_credits")) and total > 0 and credits_enforced() and not is_admin(user)
    else:
        tier_action = "brief_suggest"
        base_cost = resolve_credit_cost("content_ai", tier_action, db=db, from_cache=from_cache)
        lines = [
            {
                "key": "base",
                "module": "content_ai",
                "action": tier_action,
                "label": "Gợi ý title/meta/outline",
                "credit_cost": base_cost,
            }
        ]
        subtotal = base_cost
        mult = float(policy.get("multiplier") or 0.0) if policy.get("charge_credits") else 0.0
        total = max(0, int(round(subtotal * mult))) if mult > 0 else 0
        charge = bool(policy.get("charge_credits")) and total > 0 and credits_enforced() and not is_admin(user)

    balance = int(get_available_balance(db, user.id)) if db is not None and credits_enforced() else 0
    req_id = new_request_id()

    return {
        "module": "content_ai",
        "action": tier_action,
        "field": requested,
        "word_count": wc,
        "tier_action": tier_action,
        "label": lines[0]["label"] if lines else "Content AI",
        "credit_cost": total,
        "credit_subtotal": subtotal,
        "credit_balance": balance,
        "sufficient_credits": (not charge) or balance >= total,
        "charge_credits": charge,
        "billing_mode": policy.get("mode"),
        "billing_multiplier": mult,
        "use_system_llm": bool(use_system_llm),
        "credits_enabled": credits_enforced(),
        "request_id": req_id,
        "lines": lines,
        "flags": flags.to_dict(),
        "data_source": "api",
        "data_source_label": "Sẽ gọi LLM hệ thống sau khi xác nhận"
        if use_system_llm
        else "Dùng API key của bạn (BYOK)",
        "high_cost_warning": credits_enforced() and total >= _int_env("CREDIT_HIGH_COST_WARNING", 40),
        "high_cost_threshold": _int_env("CREDIT_HIGH_COST_WARNING", 40),
        "can_proceed": (not charge) or balance >= total,
        "breakdown": {"lines": lines, "subtotal": subtotal, "total": total, "multiplier": mult},
    }


def preview_dict_for_confirm(quote: dict[str, Any]) -> dict[str, Any]:
    """Chuẩn hóa quote cho popup DigiSeoConfirmCredit."""
    lines = quote.get("lines") or []
    breakdown = quote.get("breakdown") or {}
    if lines and not breakdown.get("lines"):
        breakdown = {**breakdown, "lines": lines}
    return {
        "credits_enabled": bool(quote.get("credits_enabled", True)),
        "module": str(quote.get("module") or "content_ai"),
        "action": str(quote.get("action") or "article_short"),
        "label": str(quote.get("label") or "Content AI"),
        "credit_cost": int(quote.get("credit_cost") or 0),
        "credit_balance": int(quote.get("credit_balance") or 0),
        "credit_balance_after": max(
            0,
            int(quote.get("credit_balance") or 0) - int(quote.get("credit_cost") or 0),
        ),
        "sufficient_credits": bool(quote.get("sufficient_credits", True)),
        "quota_key": "ai_articles",
        "quota_label": "Bài AI / tháng",
        "quota_remaining": quote.get("quota_remaining"),
        "quota_limit": quote.get("quota_limit"),
        "quota_exceeded": bool(quote.get("quota_exceeded")),
        "data_source": str(quote.get("data_source") or "api"),
        "data_source_label": str(quote.get("data_source_label") or ""),
        "high_cost_warning": bool(quote.get("high_cost_warning")),
        "high_cost_threshold": int(quote.get("high_cost_threshold") or 40),
        "can_proceed": bool(quote.get("can_proceed", True)),
        "breakdown": breakdown,
        "billing_lines": lines,
    }


def _ledger_note(quote: dict[str, Any], *, field: str, extra: dict[str, Any] | None = None) -> str:
    payload: dict[str, Any] = {
        "field": field,
        "word_count": quote.get("word_count"),
        "tier": quote.get("tier_action"),
        "project_id": (quote.get("flags") or {}).get("project_id"),
        "primary_keyword": (quote.get("flags") or {}).get("primary_keyword"),
        "billing_mode": quote.get("billing_mode"),
        "lines": [
            {"key": x.get("key"), "action": x.get("action"), "credit": x.get("credit_cost")}
            for x in (quote.get("lines") or [])
        ],
    }
    if extra:
        payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)[:500]



@dataclass
class ContentAiCreditHold:
    """Hold credits reserved before a provider call."""

    db: Session
    user: User
    amount: int
    request_id: str
    reservation_id: int | None
    feature_code: str
    field: str
    reason: str
    _done: bool = dc_field(default=False, repr=False)

    def commit(self) -> dict[str, Any] | None:
        if self._done:
            return {"request_id": self.request_id, "charged": self.amount, "already": True}
        if self.reservation_id and self.amount > 0:
            commit_reservation(
                self.db,
                reservation_id=int(self.reservation_id),
                user_id=int(self.user.id),
            )
        self._done = True
        return {
            "request_id": self.request_id,
            "charged": int(self.amount),
            "reason": self.reason,
            "reservation_id": self.reservation_id,
            "mode": "reserve_commit",
        }

    def release(self, *, reason: str = "job_failed") -> None:
        if self._done:
            return
        if self.reservation_id and self.amount > 0:
            release_reservation(
                self.db,
                reservation_id=int(self.reservation_id),
                user_id=int(self.user.id),
                reason=reason,
            )
        self._done = True


def _should_charge_quote(user: User, quote: dict[str, Any]) -> tuple[bool, int, str]:
    if not quote.get("charge_credits"):
        return False, 0, ""
    amount = int(quote.get("credit_cost") or 0)
    if not credits_enforced() or amount <= 0 or is_admin(user):
        return False, 0, ""
    req_id = str(quote.get("request_id") or new_request_id())
    return True, amount, req_id


def reserve_content_ai_write(
    db: Session,
    user: User,
    quote: dict[str, Any],
    *,
    field: str,
    feature_code: str | None = None,
) -> ContentAiCreditHold | None:
    """Reserve credits BEFORE provider/LLM. Idempotent on quote request_id."""
    ok, amount, req_id = _should_charge_quote(user, quote)
    requested = (field or "content").strip().lower()
    feat = feature_code or ("content_ai_article" if requested == "content" else "content_ai_brief")
    reason = "content_ai_article" if requested == "content" else "content_ai_brief_suggest"
    if not ok:
        return None
    quote["request_id"] = req_id
    res = reserve_credits(
        db,
        user_id=int(user.id),
        amount=amount,
        feature_code=feat,
        job_id=req_id,
        idempotency_key=f"content_ai_write:{req_id}"[:128],
        reason=f"reserve:{reason}"[:64],
        note=_ledger_note(quote, field=requested),
    )
    hold = ContentAiCreditHold(
        db=db,
        user=user,
        amount=int(res.get("amount") or amount),
        request_id=req_id,
        reservation_id=int(res["reservation_id"]) if res.get("reservation_id") else None,
        feature_code=feat,
        field=requested,
        reason=reason,
    )
    if res.get("already_committed"):
        hold._done = True
    return hold


@contextmanager
def content_ai_provider_credit_session(
    db: Session,
    user: User,
    quote: dict[str, Any],
    *,
    field: str,
    feature_code: str | None = None,
):
    """
    Reserve → yield → commit on success; release on exception / abort.
    Provider (LLM) must run inside the yielded block.
    """
    hold = reserve_content_ai_write(db, user, quote, field=field, feature_code=feature_code)
    aborted = {"v": False}

    class _Ctrl:
        def abort(self, reason: str = "aborted") -> None:
            aborted["v"] = True
            if hold is not None:
                hold.release(reason=reason)

        @property
        def hold(self) -> ContentAiCreditHold | None:
            return hold

    ctrl = _Ctrl()
    try:
        yield ctrl
        if hold is not None and not aborted["v"] and not hold._done:
            hold.commit()
    except Exception:
        if hold is not None and not hold._done:
            try:
                hold.release(reason="job_failed")
            except Exception:
                pass
        raise


def charge_content_ai_write(
    db: Session,
    user: User,
    quote: dict[str, Any],
    *,
    field: str,
    llm_used: bool,
    used_fallback: bool = False,
    hold: ContentAiCreditHold | None = None,
) -> dict[str, Any] | None:
    """
    Finalize credit: commit pre-reserved hold, or (legacy) reserve+commit once with idempotency.
    Prefer reserve-first via content_ai_provider_credit_session; this is kept for bulk paths.
    """
    if not llm_used or used_fallback:
        if hold is not None:
            hold.release(reason="fallback_or_no_llm")
        return None
    if not quote.get("charge_credits"):
        if hold is not None:
            hold.release(reason="not_chargeable")
        return None
    if hold is not None:
        return hold.commit()

    ok, amount, req_id = _should_charge_quote(user, quote)
    if not ok:
        return None
    quote["request_id"] = req_id
    # Atomic reserve-then-commit (still safe vs double-spend via idempotency_key)
    h = reserve_content_ai_write(db, user, quote, field=field)
    if h is None:
        return None
    if h._done:
        return {"request_id": h.request_id, "charged": h.amount, "mode": "idempotent"}
    return h.commit()


def charge_content_ai_from_html(
    db: Session,
    user: User,
    html: str,
    *,
    field: str = "content",
    use_system_llm: bool = True,
    flags: ContentAiBillingFlags | None = None,
    request_id: str | None = None,
    llm_used: bool = True,
    used_fallback: bool = False,
    hold: ContentAiCreditHold | None = None,
) -> dict[str, Any] | None:
    """Quote from HTML word count; commit pre-hold or reserve+commit with stable key."""
    from app.services.content_ai_word_count_policy import billing_word_count_for_content

    bill_wc = billing_word_count_for_content(html)
    quote = quote_content_ai_write(
        db,
        user,
        field=field,
        word_count=bill_wc,
        flags=flags or ContentAiBillingFlags(),
        use_system_llm=use_system_llm,
    )
    if request_id:
        quote["request_id"] = request_id
    if hold is not None:
        # Hold already took pre-estimate; commit that amount (no second debit).
        # HTML re-quote is used for logging only when costs match path.
        if not llm_used or used_fallback:
            hold.release(reason="fallback_or_no_llm")
            return None
        return hold.commit()
    return charge_content_ai_write(
        db,
        user,
        quote,
        field=field,
        llm_used=llm_used,
        used_fallback=used_fallback,
    )


def refund_content_ai_write(
    db: Session,
    user: User,
    *,
    request_id: str,
    amount: int,
    note: str = "",
) -> bool:
    """Hoàn credit khi lỗi hệ thống sau khi đã trừ."""
    if is_admin(user) or not credits_enforced():
        return False
    amt = max(0, int(amount))
    if amt <= 0:
        return False
    grant_credits(
        db,
        user_id=int(user.id),
        amount=amt,
        reason="content_ai_refund",
        note=(note or f"refund request_id={request_id}")[:500],
        source_type="refund",
    )
    return True


def should_refund_system_failure(*, charged: bool, used_fallback: bool, http_status: int | None = None) -> bool:
    if not charged:
        return False
    if used_fallback:
        return True
    if http_status is not None and http_status >= 500:
        return True
    return False

