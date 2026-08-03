"""Server-side word count validation and billing — never trust client target_word_count."""

from __future__ import annotations

import logging
import re
import time
from html import unescape
from typing import Any

from sqlalchemy.orm import Session

from app.models.user import User
from app.services.credit_cost_registry import content_ai_action_for_word_count

_LOG = logging.getLogger("content_ai.word_count")

DEFAULT_CONTENT_WORD_COUNT = 1000
WORD_COUNT_TOLERANCE_MIN = 0.90
WORD_COUNT_TOLERANCE_MAX = 1.10
REPAIR_TRIGGER_RATIO = 0.85
TRIM_TRIGGER_RATIO = 1.15

# Max words per plan slug (prompt + pre-check ceiling)
_PLAN_WORD_LIMITS: dict[str, int] = {
    "free_trial_5d": 1000,
    "starter": 1500,
    "pro": 2000,
    "agency": 3000,
    "business": 5000,
}
_DEFAULT_PLAN_WORD_LIMIT = 2000


def resolve_wc_for_content(target_word_count: int | None) -> int:
    try:
        wc_raw = int(target_word_count) if target_word_count is not None else None
    except (TypeError, ValueError):
        wc_raw = None
    if wc_raw is None or wc_raw <= 0:
        return DEFAULT_CONTENT_WORD_COUNT
    return max(200, min(wc_raw, 20000))


def is_auto_word_count_mode(mode: str | None) -> bool:
    return str(mode or "").strip().lower() == "auto"


def _outline_word_count_floor(outline: str) -> int:
    h2 = h3 = 0
    for line in str(outline or "").splitlines():
        s = line.strip()
        if s.startswith("###"):
            h3 += 1
        elif s.startswith("##"):
            h2 += 1
    if h2 <= 0 and h3 <= 0:
        return 0
    return min(20000, 150 + h2 * 90 + h3 * 45)


def resolve_auto_target_word_count(
    *,
    primary_keyword: str = "",
    outline_content: str = "",
    title: str = "",
    user: User,
    db: Session | None = None,
) -> int:
    """AI chọn độ dài phù hợp theo từ khóa, chủ đề (title) và intent."""
    from app.services.content_draft_builder import detect_search_intent

    pk = str(primary_keyword or title or "").strip()
    intent = detect_search_intent(pk) if pk else "informational"
    kw_lower = pk.lower()

    if intent in {"transactional", "ecommerce"}:
        base = 1000
    elif intent == "commercial":
        base = 1500
    elif intent in {"informational", "navigational"}:
        base = 1800
    else:
        base = 1500

    if any(x in kw_lower for x in ("hướng dẫn", "huong dan", "cách ", "cach ", "quy trình", "quy trinh")):
        base = max(base, 2000)
    if any(x in kw_lower for x in ("so sánh", "so sanh", "top ", "review", "đánh giá", "danh gia")):
        base = max(base, 1600)
    if any(x in kw_lower for x in ("dịch vụ", "dich vu", "giá ", "gia ", "bảng giá", "bang gia")):
        base = max(base, 1200)

    floor = _outline_word_count_floor(str(outline_content or "").strip())
    if floor:
        base = max(base, floor)

    return validate_target_word_count(base, user, db)


def resolve_content_target_word_count(
    client_value: int | None,
    mode: str | None,
    user: User,
    db: Session | None = None,
    *,
    primary_keyword: str = "",
    outline_content: str = "",
    title: str = "",
) -> tuple[int, bool]:
    """Trả về (validated_wc, was_auto)."""
    if is_auto_word_count_mode(mode):
        return (
            resolve_auto_target_word_count(
                primary_keyword=primary_keyword,
                outline_content=outline_content,
                title=title,
                user=user,
                db=db,
            ),
            True,
        )
    return validate_target_word_count(client_value, user, db), False


def word_count_from_html(html: str) -> int:
    raw = str(html or "")
    text = re.sub(r"<[^>]+>", " ", raw)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return len(text.split()) if text else 0


def word_count_bounds(validated: int) -> tuple[int, int]:
    wc = max(200, min(int(validated), 20000))
    return int(wc * WORD_COUNT_TOLERANCE_MIN), int(wc * WORD_COUNT_TOLERANCE_MAX)


def repair_trigger_min(validated: int) -> int:
    return int(max(200, min(int(validated), 20000)) * REPAIR_TRIGGER_RATIO)


def trim_trigger_max(validated: int) -> int:
    return int(max(200, min(int(validated), 20000)) * TRIM_TRIGGER_RATIO)


def word_count_status(actual: int, validated: int) -> str:
    """ok | short | long — UI band ±10%."""
    min_ok, max_ok = word_count_bounds(validated)
    if actual < min_ok:
        return "short"
    if actual > max_ok:
        return "long"
    return "ok"


def needs_word_count_repair(actual: int, validated: int) -> bool:
    """Trigger LLM expand when more than 15% below target."""
    return int(actual) < repair_trigger_min(validated)


def needs_word_count_trim(actual: int, validated: int) -> bool:
    """Trigger LLM trim when more than 15% above target."""
    return int(actual) > trim_trigger_max(validated)


def _user_plan_slug(user: User, db: Session | None) -> str:
    slug = str(getattr(user, "plan_slug", None) or getattr(user, "plan", None) or "").strip().lower()
    if slug:
        return slug
    if db is None:
        return ""
    try:
        from app.services.entitlement_service import get_user_plan_slug

        return str(get_user_plan_slug(db, int(user.id)) or "").strip().lower()
    except Exception:
        return ""


def plan_max_word_count(user: User, db: Session | None = None) -> int:
    slug = _user_plan_slug(user, db)
    return int(_PLAN_WORD_LIMITS.get(slug, _DEFAULT_PLAN_WORD_LIMIT))


def validate_target_word_count(
    client_value: int | None,
    user: User,
    db: Session | None = None,
) -> int:
    """Clamp client target to global bounds and plan limit — used for LLM prompt."""
    resolved = resolve_wc_for_content(client_value)
    plan_cap = plan_max_word_count(user, db)
    return max(200, min(resolved, plan_cap))


def resolve_word_counts(
    client_value: int | None,
    user: User,
    db: Session | None = None,
) -> dict[str, int]:
    """Normalize client input → requested (parsed) + validated (plan-clamped)."""
    return {
        "requested_word_count": resolve_wc_for_content(client_value),
        "validated_word_count": validate_target_word_count(client_value, user, db),
    }


def assess_word_count_meta(html: str, validated_word_count: int) -> dict[str, Any]:
    actual = word_count_from_html(html)
    validated = int(validated_word_count)
    min_ok, max_ok = word_count_bounds(validated)
    status = word_count_status(actual, validated)
    return {
        "validated_word_count": validated,
        "actual_word_count": actual,
        "word_count_status": status,
        "word_count_min": min_ok,
        "word_count_max": max_ok,
        "word_count_ok": status == "ok",
        "needs_repair": needs_word_count_repair(actual, validated),
        "needs_trim": needs_word_count_trim(actual, validated),
        # legacy aliases for existing JS/API consumers
        "word_count_target": validated,
        "word_count_actual": actual,
    }


def build_word_count_response(
    *,
    client_value: int | None,
    user: User,
    db: Session | None,
    html: str,
) -> dict[str, Any]:
    counts = resolve_word_counts(client_value, user, db)
    meta = assess_word_count_meta(html, counts["validated_word_count"])
    return {
        "requested_word_count": counts["requested_word_count"],
        **meta,
        "skip_client_enforce": not meta["needs_repair"] and not meta["needs_trim"],
    }


def billing_word_count_for_content(html: str) -> int:
    """Credit tier is based on actual generated output, not client request."""
    return max(0, word_count_from_html(html))


def billing_tier_action_for_html(html: str) -> str:
    return content_ai_action_for_word_count(billing_word_count_for_content(html))


def precheck_word_count_for_gate(user: User, client_value: int | None, db: Session | None = None) -> int:
    """
    Conservative pre-check: use plan max so user cannot pass gate with low count
    then receive (and be under-charged for) a much longer article.
    """
    validated = validate_target_word_count(client_value, user, db)
    return max(validated, plan_max_word_count(user, db))


def chatbot_validated_word_count(user_id: int, client_value: int | None) -> int:
    """Resolve validated word count for chatbot SEO write workflows."""
    from app.db import SessionLocal
    from app.models.user import User

    db = SessionLocal()
    try:
        user = db.get(User, int(user_id))
        if not user:
            stub = User(id=int(user_id), email="", password_hash="", role="user", status="active")
            return validate_target_word_count(client_value, stub, db)
        return validate_target_word_count(client_value, user, db)
    finally:
        db.close()


def log_word_count_event(
    *,
    user_id: int,
    endpoint: str,
    requested: int,
    validated: int,
    actual: int,
    status: str,
    duration_ms: int | None = None,
    request_id: str | None = None,
) -> None:
    """Safe debug log — no API keys, no full HTML."""
    _LOG.info(
        "word_count user_id=%s endpoint=%s requested=%s validated=%s actual=%s status=%s duration_ms=%s request_id=%s",
        int(user_id),
        str(endpoint or "")[:80],
        int(requested),
        int(validated),
        int(actual),
        str(status or "")[:16],
        int(duration_ms) if duration_ms is not None else "",
        str(request_id or "")[:64],
    )


class WordCountTimer:
    def __init__(self) -> None:
        self._t0 = time.perf_counter()

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self._t0) * 1000)
