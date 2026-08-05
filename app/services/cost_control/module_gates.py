"""Cost gates for Content AI and Chatbot CSKH modules."""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Iterator

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.cost_control.gate import CostGateRequest, CostGateSession, cost_gate_session
from app.services.cost_control.types import ExternalApiProvider

if TYPE_CHECKING:
    from app.services.llm_content_writer import LlmConfig


def llm_provider_for_config(cfg: LlmConfig | None) -> ExternalApiProvider:
    if cfg is not None and str(cfg.provider or "").strip().lower() == "anthropic":
        return ExternalApiProvider.ANTHROPIC
    return ExternalApiProvider.OPENAI


@contextmanager
def content_ai_llm_gate(
    db: Session,
    user: User,
    *,
    action: str,
    field: str = "content",
    use_system_llm: bool = True,
    llm_cfg: LlmConfig | None = None,
    feature_key: str | None = None,
    credit_cost: int | None = None,
    word_count: int | None = None,
    skip_credit_check: bool | None = None,
) -> Iterator[CostGateSession]:
    """Gate trước mọi gọi LLM Content AI — luôn dùng API hệ thống cho user thường."""
    from app.services.content_ai_entitlement import bypass_entitlement, feature_for_suggest_field
    from app.services.credits import cost_content_ai_article, cost_content_ai_brief_suggest
    from app.services.rbac import is_admin

    fk = feature_key or feature_for_suggest_field(field)
    bypass = bypass_entitlement(user)
    system_llm = True if not is_admin(user) else bool(use_system_llm)
    if bypass:
        cost = 0
        skip_credit = True
        require_paid = False
    elif system_llm:
        if credit_cost is not None:
            cost = max(0, int(credit_cost))
        else:
            cost = cost_content_ai_article(word_count=word_count, db=db) if (field or "").strip().lower() == "content" else cost_content_ai_brief_suggest(db=db)
        skip_credit = False
        require_paid = True
    else:
        cost = 0
        skip_credit = True
        require_paid = False
    if skip_credit_check is not None:
        skip_credit = bool(skip_credit_check)

    provider = llm_provider_for_config(llm_cfg)
    req = CostGateRequest(
        db=db,
        user=user,
        provider=provider,
        action=action,
        credit_cost=cost,
        feature_key=fk if not bypass else None,
        quota_units=1,
        require_paid_plan=require_paid,
        skip_credit_check=skip_credit,
        single_flight_key=f"content_ai:{user.id}:{action}:{field}",
    )
    with cost_gate_session(req) as session:
        yield session


@contextmanager
def content_ai_cse_gate(
    db: Session,
    user: User,
    *,
    action: str,
    credit_cost: int | None = None,
) -> Iterator[CostGateSession]:
    """Gate trước Google CSE / tìm ảnh."""
    from app.services.content_ai_entitlement import bypass_entitlement
    from app.services.credits import cost_chatbot_google_image

    bypass = bypass_entitlement(user)
    cost = max(0, int(credit_cost if credit_cost is not None else cost_chatbot_google_image()))
    req = CostGateRequest(
        db=db,
        user=user,
        provider=ExternalApiProvider.GOOGLE_CSE,
        action=action,
        credit_cost=cost,
        feature_key="image_generate" if not bypass else None,
        quota_units=1,
        skip_credit_check=bypass or cost <= 0,
        single_flight_key=f"content_ai_cse:{user.id}:{action}",
    )
    with cost_gate_session(req) as session:
        yield session


@contextmanager
def content_ai_crawl_gate(
    db: Session,
    user: User,
    *,
    action: str,
    url: str = "",
    credit_cost: int = 0,
) -> Iterator[CostGateSession]:
    """Gate trước crawl URL (outline đối thủ, v.v.)."""
    from app.services.content_ai_entitlement import bypass_entitlement

    bypass = bypass_entitlement(user)
    url_key = hashlib.sha256(str(url or action).encode("utf-8")).hexdigest()[:16]
    req = CostGateRequest(
        db=db,
        user=user,
        provider=ExternalApiProvider.CRAWL,
        action=action,
        credit_cost=max(0, int(credit_cost)),
        skip_credit_check=bypass or credit_cost <= 0,
        single_flight_key=f"content_ai_crawl:{user.id}:{url_key}",
    )
    with cost_gate_session(req) as session:
        yield session


@contextmanager
def chatbot_cskh_llm_gate(
    db: Session,
    owner: User,
    *,
    action: str,
    bot_id: int,
    llm_cfg: LlmConfig | None = None,
) -> Iterator[CostGateSession]:
    """Gate trước LLM trả lời Chatbot CSKH (quota tháng + rate limit)."""
    from app.services.cau_ai_fix_entitlement import resolve_cau_ai_plan_slug
    from app.services.chatbot_cskh_credits import assert_can_consume_reply

    plan_slug = resolve_cau_ai_plan_slug(db, owner)
    if not plan_slug:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "plan_required",
                "message": "Chatbot tạm ngưng — chủ website cần nâng cấp gói SEOAuto.",
                "upgrade_url": "/pricing",
            },
        )
    from app.services.saas_gate import enforce_saas_access
    enforce_saas_access(db, owner, feature_code="chatbot_cskh_reply", quantity=1, require_feature=True)
    assert_can_consume_reply(db, owner.id, plan_slug)

    provider = llm_provider_for_config(llm_cfg)
    req = CostGateRequest(
        db=db,
        user=owner,
        provider=provider,
        action=action,
        credit_cost=0,
        feature_key="chatbot_cskh_reply",
        require_paid_plan=True,
        skip_credit_check=True,
        single_flight_key=f"cskh_llm:{owner.id}:{bot_id}:{action}",
        rate_limit_per_min=20,
    )
    with cost_gate_session(req) as session:
        yield session


@contextmanager
def chatbot_cskh_crawl_gate(
    db: Session,
    user: User,
    *,
    action: str,
    url: str,
) -> Iterator[CostGateSession]:
    """Gate trước crawl trang cho knowledge CSKH."""
    from app.services.cau_ai_fix_entitlement import resolve_cau_ai_plan_slug

    if not resolve_cau_ai_plan_slug(db, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "plan_required", "message": "Cần gói Basic trở lên để crawl nguồn tri thức."},
        )
    url_key = hashlib.sha256(str(url or "").encode("utf-8")).hexdigest()[:16]
    req = CostGateRequest(
        db=db,
        user=user,
        provider=ExternalApiProvider.CRAWL,
        action=action,
        credit_cost=0,
        require_paid_plan=True,
        skip_credit_check=True,
        single_flight_key=f"cskh_crawl:{user.id}:{url_key}",
    )
    with cost_gate_session(req) as session:
        yield session


@contextmanager
def cau_ai_fix_gate(
    db: Session,
    user: User,
    *,
    action: str,
    llm_cfg: LlmConfig | None = None,
) -> Iterator[CostGateSession]:
    """Gate cho Auto Update AI fix (đã assert entitlement ở router)."""
    from app.services.credits import cost_cau_seo_ai_fix

    with content_ai_llm_gate(
        db,
        user,
        action=action,
        field="content",
        use_system_llm=True,
        llm_cfg=llm_cfg,
        feature_key="content_auto_update_generate",
        credit_cost=cost_cau_seo_ai_fix(),
    ) as session:
        yield session


@contextmanager
def seo_score_ai_fix_gate(
    db: Session,
    user: User,
    *,
    action: str = "ai_fix",
    llm_cfg: LlmConfig | None = None,
) -> Iterator[CostGateSession]:
    """Gate trước LLM sửa từng trường SEO Score (registry: seo_score/ai_fix)."""
    from app.services.content_ai_entitlement import bypass_entitlement
    from app.services.credits import cost_seo_score_ai_fix
    from app.services.seo_score_ai_fix import seo_score_ai_fix_billing_enabled

    bypass = bypass_entitlement(user)
    billing = seo_score_ai_fix_billing_enabled()
    if bypass:
        cost = 0
        skip_credit = True
        require_paid = False
    elif billing:
        cost = cost_seo_score_ai_fix(db=db)
        skip_credit = False
        require_paid = True
    else:
        cost = 0
        skip_credit = True
        require_paid = True

    provider = llm_provider_for_config(llm_cfg)
    req = CostGateRequest(
        db=db,
        user=user,
        provider=provider,
        action=action,
        credit_cost=cost,
        feature_key="seo_score" if not bypass else None,
        quota_units=1,
        require_paid_plan=require_paid,
        skip_credit_check=skip_credit,
        single_flight_key=f"seo_score_ai_fix:{user.id}:{action}",
    )
    with cost_gate_session(req) as session:
        yield session
