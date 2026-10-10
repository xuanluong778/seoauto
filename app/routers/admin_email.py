"""Admin UI + APIs for Email Automation and Email Marketing."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.email_automation_marketing import (
    AUTOMATION_EMAIL_TYPES,
    CAMPAIGN_STATUS_CANCELLED,
    CAMPAIGN_STATUS_DRAFT,
    CAMPAIGN_STATUS_SCHEDULED,
    CAMPAIGN_STATUS_SENDING,
    CAMPAIGN_STATUS_SENT,
    EmailAutomationTemplate,
    EmailMarketingCampaign,
    EmailMarketingUnsubscribe,
    EmailSend,
    EmailSendLog,
)
from app.models.user import User
from app.schemas.admin_email import (
    EmailAiComposeRequest,
    EmailAutomationTemplateSave,
    EmailMarketingCampaignCreate,
    EmailPreviewRequest,
    EmailTestSendRequest,
)
from app.workers.email_automation_marketing_worker import (
    email_automation_tick_task,
    email_marketing_send_campaign_task,
)
from app.services.rbac import require_admin_user
from app.services.email_html_sanitize import sanitize_email_html, validate_image_url, validate_link_url
from app.services.email_automation_marketing_engine import (
    list_segment_recipients,
    preview_mapping,
    render_email_preview,
)
from app.services.credit_cost_registry import resolve_credit_cost
from app.services.saas_gate import saas_action_gate
from app.services.cost_usage_logger import record_infra_cost_usage
from app.services.mail_smtp import send_email


_LOG = logging.getLogger(__name__)

router = APIRouter(prefix="/email", tags=["admin-email"])


def _admin_id(admin: User) -> int:
    return int(admin.id)


def _aware_utc(dt: datetime | None, tz_name: str) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        try:
            from zoneinfo import ZoneInfo

            dt = dt.replace(tzinfo=ZoneInfo(tz_name or "Asia/Ho_Chi_Minh"))
        except Exception:
            dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _org_id(user_id: int) -> int | None:
    try:
        from app.services.tenant_org import personal_organization_id

        return personal_organization_id(int(user_id))
    except Exception:
        return None


def _campaign_item(r: EmailMarketingCampaign) -> dict[str, Any]:
    return {
        "id": int(r.id),
        "name": r.name,
        "status": r.status,
        "segment_kind": r.segment_kind,
        "send_mode": r.send_mode,
        "subject": r.subject,
        "preheader": getattr(r, "preheader", None),
        "timezone": getattr(r, "timezone", None) or "Asia/Ho_Chi_Minh",
        "scheduled_at": r.scheduled_at.isoformat() if r.scheduled_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("/automation/templates")
def admin_list_automation_templates(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
):
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    try:
        db.execute(text("SET LOCAL lock_timeout = '3s'"))
        db.execute(text("SET LOCAL statement_timeout = '8s'"))
        rows = db.execute(
            text(
                """
                SELECT id, email_type, enabled, name, subject_template,
                       html_body_template, text_body_template
                FROM email_automation_templates
                WHERE owner_user_id = :oid
                ORDER BY email_type
                """
            ),
            {"oid": _admin_id(admin)},
        ).mappings().all()
    except OperationalError:
        _LOG.warning("email automation templates query timed out / failed", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        return {"items": [], "email_types": sorted(AUTOMATION_EMAIL_TYPES)}
    return {
        "items": [
            {
                "id": int(r["id"]),
                "email_type": r["email_type"],
                "enabled": bool(r["enabled"]),
                "name": r["name"],
                "subject_template": r["subject_template"],
                "preheader_template": None,
                "html_body_template": r["html_body_template"],
                "text_body_template": r["text_body_template"],
            }
            for r in rows
        ],
        "email_types": sorted(AUTOMATION_EMAIL_TYPES),
    }


@router.post("/automation/templates/save")
def admin_save_automation_template(
    body: EmailAutomationTemplateSave,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
):
    from sqlalchemy import text

    owner_id = _admin_id(admin)
    email_type = str(body.email_type).strip()
    if email_type not in AUTOMATION_EMAIL_TYPES:
        raise HTTPException(status_code=400, detail="email_type không hợp lệ.")
    html_body = sanitize_email_html(str(body.html_body_template or ""))
    name = str(body.name or "").strip()[:160] or "Automation Template"
    subject = str(body.subject_template or "").strip()[:255]
    text_body = str(body.text_body_template or "").strip()[:4000] if body.text_body_template else None
    enabled = bool(body.enabled)

    existing = db.execute(
        text(
            "SELECT id FROM email_automation_templates WHERE owner_user_id=:oid AND email_type=:etype LIMIT 1"
        ),
        {"oid": owner_id, "etype": email_type},
    ).first()
    if existing is None:
        row = db.execute(
            text(
                """
                INSERT INTO email_automation_templates
                  (owner_user_id, email_type, enabled, name, subject_template, html_body_template, text_body_template)
                VALUES
                  (:oid, :etype, :enabled, :name, :subject, :html, :text)
                RETURNING id
                """
            ),
            {
                "oid": owner_id,
                "etype": email_type,
                "enabled": enabled,
                "name": name,
                "subject": subject,
                "html": html_body,
                "text": text_body,
            },
        )
        item_id = int(row.scalar_one())
    else:
        item_id = int(existing[0])
        db.execute(
            text(
                """
                UPDATE email_automation_templates
                SET enabled=:enabled, name=:name, subject_template=:subject,
                    html_body_template=:html, text_body_template=:text
                WHERE id=:id
                """
            ),
            {
                "enabled": enabled,
                "name": name,
                "subject": subject,
                "html": html_body,
                "text": text_body,
                "id": item_id,
            },
        )
    db.commit()
    try:
        db.execute(
            text(
                "UPDATE email_automation_templates SET preheader_template=:p WHERE id=:id"
            ),
            {"p": str(body.preheader_template or "").strip()[:180] or None, "id": item_id},
        )
        db.commit()
    except Exception:
        db.rollback()
        _LOG.warning("optional preheader_template update skipped id=%s", item_id, exc_info=True)
    return {"ok": True, "item": item_id}


@router.post("/automation/tick")
def admin_trigger_automation_tick(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
):
    email_automation_tick_task.delay()
    return {"ok": True}


@router.get("/campaigns")
def admin_list_campaigns(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
    limit: int = 50,
    offset: int = 0,
):
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    owner_id = _admin_id(admin)
    lim = max(1, min(int(limit), 200))
    off = max(0, int(offset))
    # Raw SQL avoids UndefinedColumn if additive columns not migrated yet.
    try:
        db.execute(text("SET LOCAL lock_timeout = '3s'"))
        db.execute(text("SET LOCAL statement_timeout = '8s'"))
        rows = db.execute(
            text(
                """
                SELECT id, name, status, segment_kind, send_mode, subject,
                       scheduled_at, created_at
                FROM email_marketing_campaigns
                WHERE owner_user_id = :oid
                ORDER BY created_at DESC
                LIMIT :lim OFFSET :off
                """
            ),
            {"oid": owner_id, "lim": lim, "off": off},
        ).mappings().all()
    except OperationalError:
        _LOG.warning("email campaigns list timed out / failed", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        return {"items": []}
    items = []
    for r in rows:
        items.append(
            {
                "id": int(r["id"]),
                "name": r["name"],
                "status": r["status"],
                "segment_kind": r["segment_kind"],
                "send_mode": r["send_mode"],
                "subject": r["subject"],
                "preheader": None,
                "timezone": "Asia/Ho_Chi_Minh",
                "scheduled_at": r["scheduled_at"].isoformat() if r["scheduled_at"] else None,
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
        )
    return {"items": items}


@router.get("/segment-recipients")
def admin_list_segment_recipients(
    kind: str = "active",
    plan_id: int | None = None,
    q: str | None = None,
    limit: int = 500,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
):
    """List emails matching a campaign segment so admin can pick recipients."""
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    kind_n = str(kind or "active").strip().lower()
    allowed = {"all", "trial", "active", "expired", "low_credit", "by_plan"}
    if kind_n not in allowed:
        raise HTTPException(status_code=400, detail="segment kind không hợp lệ.")
    try:
        db.execute(text("SET LOCAL lock_timeout = '3s'"))
        db.execute(text("SET LOCAL statement_timeout = '12s'"))
        rows = list_segment_recipients(
            db,
            segment_kind=kind_n,
            segment_plan_id=plan_id,
            q=q,
            limit=limit,
        )
    except OperationalError:
        _LOG.warning("segment recipients query timed out", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        return {"items": [], "total": 0, "kind": kind_n}
    items = [
        {
            "user_id": r["user_id"],
            "email": r["email"],
            "name": r["name"],
            "plan_name": r["plan_name"],
            "expiry_date": r["expiry_date"],
            "credit_balance": r["credit_balance"],
        }
        for r in rows
    ]
    return {"items": items, "total": len(items), "kind": kind_n}


def _preseed_campaign_recipients(
    db: Session,
    *,
    owner_id: int,
    campaign_id: int,
    segment_kind: str,
    segment_plan_id: int | None,
    recipient_user_ids: list[int],
) -> int:
    """Create queued EmailSend rows for the selected users only."""
    wanted = {int(x) for x in recipient_user_ids if int(x) > 0}
    if not wanted:
        return 0
    pool = list_segment_recipients(
        db,
        segment_kind=segment_kind,
        segment_plan_id=segment_plan_id,
        limit=2000,
    )
    by_id = {int(r["user_id"]): r for r in pool}
    created = 0
    for uid in wanted:
        rcpt = by_id.get(uid)
        if not rcpt:
            continue
        email = str(rcpt["email"]).strip().lower()
        unsub = db.execute(
            select(EmailMarketingUnsubscribe).where(
                EmailMarketingUnsubscribe.owner_user_id == owner_id,
                EmailMarketingUnsubscribe.recipient_email == email,
            )
        ).scalar_one_or_none()
        if unsub is not None and unsub.unsubscribed_at is not None:
            continue
        if unsub is None:
            unsub = EmailMarketingUnsubscribe(
                owner_user_id=owner_id,
                recipient_email=email,
                unsub_token=uuid.uuid4().hex,
                unsubscribed_at=None,
            )
            db.add(unsub)
            db.flush()
        exp = rcpt.get("expiry_date_obj")
        outbox = EmailSend(
            owner_user_id=owner_id,
            campaign_id=int(campaign_id),
            recipient_user_id=uid,
            recipient_email=email,
            recipient_name=rcpt.get("name"),
            automation_email_type=None,
            plan_name=rcpt.get("plan_name"),
            expiry_date=exp,
            discount_code=None,
            status="queued",
            attempt_count=0,
            max_retries=3,
            event_token=uuid.uuid4().hex,
            unsub_token=unsub.unsub_token,
            click_target_url=None,
        )
        db.add(outbox)
        db.flush()
        db.add(
            EmailSendLog(
                owner_user_id=owner_id,
                email_send_id=int(outbox.id),
                recipient_email=email,
                status="queued",
                detail=f"marketing:{campaign_id}:selected",
            )
        )
        created += 1
    db.commit()
    return created


@router.post("/campaigns")
def admin_create_campaign(
    body: EmailMarketingCampaignCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
):
    owner_id = _admin_id(admin)
    try:
        cta_url = validate_link_url(str(body.cta_url or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    html_body = sanitize_email_html(str(body.html_body or ""))
    if not html_body:
        raise HTTPException(status_code=400, detail="HTML body trống sau khi lọc XSS.")
    tz_name = str(body.timezone or "Asia/Ho_Chi_Minh")[:64]
    scheduled_at = _aware_utc(body.scheduled_at, tz_name)
    send_mode = str(body.send_mode)
    if send_mode == "draft":
        status = CAMPAIGN_STATUS_DRAFT
    elif send_mode == "scheduled":
        if not scheduled_at:
            raise HTTPException(status_code=400, detail="Thiếu scheduled_at (timezone).")
        status = CAMPAIGN_STATUS_SCHEDULED
    else:
        status = CAMPAIGN_STATUS_DRAFT

    selected_ids = [int(x) for x in (body.recipient_user_ids or []) if int(x) > 0]
    if body.recipient_user_ids is not None and send_mode != "draft" and not selected_ids:
        raise HTTPException(
            status_code=400,
            detail="Chưa chọn email nhận. Chọn ít nhất 1 Gmail trong danh sách segment.",
        )

    # Insert via core columns first (compatible if additive cols missing),
    # then best-effort update optional fields.
    from sqlalchemy import text

    result = db.execute(
        text(
            """
            INSERT INTO email_marketing_campaigns
              (owner_user_id, name, subject, html_body, text_body, cta_label, cta_url,
               discount_code, segment_kind, segment_plan_id, send_mode, scheduled_at, status)
            VALUES
              (:owner_user_id, :name, :subject, :html_body, :text_body, :cta_label, :cta_url,
               :discount_code, :segment_kind, :segment_plan_id, :send_mode, :scheduled_at, :status)
            RETURNING id
            """
        ),
        {
            "owner_user_id": owner_id,
            "name": str(body.name or "").strip()[:200],
            "subject": str(body.subject or "").strip()[:255],
            "html_body": html_body,
            "text_body": str(body.text_body or "").strip()[:4000] if body.text_body else None,
            "cta_label": str(body.cta_label or "").strip()[:120] or "Mở ngay",
            "cta_url": cta_url,
            "discount_code": str(body.discount_code).strip()[:80] if body.discount_code else None,
            "segment_kind": str(body.segment_kind),
            "segment_plan_id": int(body.segment_plan_id) if body.segment_plan_id else None,
            "send_mode": send_mode,
            "scheduled_at": scheduled_at,
            "status": status,
        },
    )
    camp_id = int(result.scalar_one())
    db.commit()
    try:
        db.execute(
            text(
                """
                UPDATE email_marketing_campaigns
                SET preheader = :preheader, timezone = :timezone
                WHERE id = :id
                """
            ),
            {
                "preheader": str(body.preheader or "").strip()[:180] or None,
                "timezone": tz_name,
                "id": camp_id,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        _LOG.warning("optional campaign columns update skipped id=%s", camp_id, exc_info=True)

    seeded = 0
    if selected_ids:
        try:
            seeded = _preseed_campaign_recipients(
                db,
                owner_id=owner_id,
                campaign_id=camp_id,
                segment_kind=str(body.segment_kind),
                segment_plan_id=int(body.segment_plan_id) if body.segment_plan_id else None,
                recipient_user_ids=selected_ids,
            )
        except Exception:
            _LOG.exception("preseed campaign recipients failed id=%s", camp_id)
            raise HTTPException(
                status_code=500,
                detail="Không tạo được danh sách email đã chọn. Thử lại.",
            ) from None
        if send_mode != "draft" and seeded <= 0:
            raise HTTPException(
                status_code=400,
                detail="Không có email hợp lệ trong lựa chọn (có thể đã unsubscribe).",
            )

    if send_mode == "now":
        email_marketing_send_campaign_task.delay(int(camp_id))
    return {
        "ok": True,
        "id": int(camp_id),
        "status": status,
        "recipients_selected": len(selected_ids),
        "recipients_queued": seeded,
    }


@router.post("/campaigns/{campaign_id}/send-now")
def admin_send_campaign_now(
    campaign_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
):
    owner_id = _admin_id(admin)
    camp = db.get(EmailMarketingCampaign, int(campaign_id))
    if camp is None or int(camp.owner_user_id) != owner_id:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    if str(camp.status) in {CAMPAIGN_STATUS_SENDING, CAMPAIGN_STATUS_SENT}:
        raise HTTPException(status_code=409, detail="Campaign đang gửi hoặc đã gửi — chống duplicate.")
    if str(camp.status) == CAMPAIGN_STATUS_CANCELLED:
        raise HTTPException(status_code=409, detail="Campaign đã huỷ.")
    camp.status = CAMPAIGN_STATUS_SENDING
    camp.send_mode = "now"
    db.commit()
    email_marketing_send_campaign_task.delay(int(campaign_id))
    return {"ok": True}


@router.post("/campaigns/{campaign_id}/cancel")
def admin_cancel_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
):
    camp = db.get(EmailMarketingCampaign, int(campaign_id))
    if camp is None or int(camp.owner_user_id) != _admin_id(admin):
        raise HTTPException(status_code=404, detail="Campaign not found.")
    if str(camp.status) == CAMPAIGN_STATUS_SENT:
        raise HTTPException(status_code=409, detail="Campaign đã gửi xong.")
    camp.status = CAMPAIGN_STATUS_CANCELLED
    db.commit()
    return {"ok": True, "status": camp.status}


@router.get("/history")
def admin_email_history(
    status: str | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
    limit: int = 50,
    offset: int = 0,
):
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    owner_id = _admin_id(admin)
    try:
        db.execute(text("SET LOCAL lock_timeout = '3s'"))
        db.execute(text("SET LOCAL statement_timeout = '8s'"))
        q = select(EmailSendLog).where(EmailSendLog.owner_user_id == owner_id)
        if status:
            q = q.where(EmailSendLog.status == str(status).strip().lower())
        rows = (
            db.execute(
                q.order_by(EmailSendLog.created_at.desc())
                .limit(max(1, min(int(limit), 200)))
                .offset(max(0, int(offset)))
            )
            .scalars()
            .all()
        )
    except OperationalError:
        _LOG.warning("email history timed out / failed", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        return {"items": []}
    return {
        "items": [
            {
                "id": r.id,
                "status": r.status,
                "recipient_email": r.recipient_email,
                "detail": r.detail,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.get("/stats")
def admin_email_stats(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
):
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    owner_id = _admin_id(admin)
    empty = {
        "delivered": 0,
        "opened": 0,
        "clicked": 0,
        "bounced": 0,
        "unsubscribed": 0,
        "failed": 0,
        "queued": 0,
        "by_status": {},
    }
    try:
        db.execute(text("SET LOCAL lock_timeout = '3s'"))
        db.execute(text("SET LOCAL statement_timeout = '8s'"))
        rows = db.execute(
            select(EmailSend.status, func.count(EmailSend.id))
            .where(EmailSend.owner_user_id == owner_id)
            .group_by(EmailSend.status)
        ).all()
    except OperationalError:
        _LOG.warning("email stats timed out / failed", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        return empty
    counts = {str(k): int(v) for k, v in rows}
    return {
        "delivered": counts.get("delivered", 0) + counts.get("sent", 0),
        "opened": counts.get("opened", 0),
        "clicked": counts.get("clicked", 0),
        "bounced": counts.get("bounced", 0),
        "unsubscribed": counts.get("unsubscribed", 0),
        "failed": counts.get("failed", 0),
        "queued": counts.get("queued", 0),
        "by_status": counts,
    }


@router.post("/ai/compose")
def admin_email_ai_compose(
    body: EmailAiComposeRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
):
    from app.services.cost_control.executor import CostControlBypassError
    from app.services.cost_control.module_gates import email_ai_composer_gate
    from app.services.email_ai_composer import compose_email
    from app.services.llm_content_writer import load_llm_config, load_llm_config_admin

    action = str(body.action or "generate")
    feature = "email.rewrite" if action != "generate" else "email.compose"
    cost = int(resolve_credit_cost("email", "rewrite" if action != "generate" else "compose", db=db) or 0)
    job_id = f"email-ai:{admin.id}:{uuid.uuid4().hex[:12]}"
    llm_cfg = load_llm_config(user_id=int(admin.id)) or load_llm_config_admin()
    if llm_cfg is None:
        raise HTTPException(
            status_code=503,
            detail="Chưa cấu hình LLM cho Email Composer. Vào Admin → LLM Settings.",
        )
    try:
        with saas_action_gate(
            db,
            admin,
            feature_code=feature,
            credit_cost=cost,
            job_id=job_id,
            require_feature=False,
            auto_commit_on_success=True,
        ):
            # Cost control requires an active openai/anthropic gate around LLM HTTP.
            with email_ai_composer_gate(db, admin, action="chat_completion", llm_cfg=llm_cfg):
                result = compose_email(
                    action=action,
                    goal=body.goal,
                    segment=body.segment,
                    tone=body.tone,
                    offer=body.offer,
                    cta_label=body.cta_label,
                    cta_url=body.cta_url,
                    current_subject=body.current_subject,
                    current_html=body.current_html,
                    user_id=int(admin.id),
                )
    except HTTPException:
        raise
    except CostControlBypassError:
        _LOG.exception("email ai compose blocked by cost control")
        raise HTTPException(
            status_code=503,
            detail="AI Composer tạm bị chặn bởi kiểm soát chi phí. Vui lòng thử lại.",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc) or "AI Composer thất bại.") from exc
    except Exception as exc:
        _LOG.exception("email ai compose failed")
        raise HTTPException(
            status_code=502,
            detail="Không thể soạn email bằng AI. Vui lòng thử lại sau.",
        ) from exc
    try:
        record_infra_cost_usage(
            db,
            user_id=int(admin.id),
            organization_id=_org_id(int(admin.id)),
            feature_key=feature.replace(".", "_"),
            quantity=1,
            provider=str(result.get("provider") or "llm"),
            request_id=job_id,
            credits_used=cost,
            estimated_cost=max(80, cost * 80),
        )
        db.commit()
    except Exception:
        db.rollback()
        _LOG.exception("email ai meter failed")
    return {"ok": True, "credits_used": cost, **{k: v for k, v in result.items() if k != "provider"}}


@router.post("/preview")
def admin_email_preview(
    body: EmailPreviewRequest,
    admin: User = Depends(require_admin_user),
):
    mapping = preview_mapping(
        name=body.name,
        plan=body.plan,
        expiry_date=body.expiry_date,
        credit_balance=body.credit_balance,
        cta_url=body.cta_url or "https://seoauto.vn/account-billing",
    )
    rendered = render_email_preview(
        subject=body.subject,
        html_body=body.html_body,
        text_body=body.text_body,
        preheader=body.preheader,
        cta_label=body.cta_label,
        cta_url=body.cta_url,
        mapping=mapping,
    )
    return {"ok": True, **rendered}


@router.post("/test-send")
def admin_email_test_send(
    body: EmailTestSendRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
):
    to = str(body.to or admin.email or "").strip().lower()
    if "@" not in to:
        raise HTTPException(status_code=400, detail="Email test không hợp lệ.")
    mapping = preview_mapping(email=to, cta_url=body.cta_url or "https://seoauto.vn/account-billing")
    rendered = render_email_preview(
        subject=body.subject,
        html_body=body.html_body,
        text_body=body.text_body,
        preheader=body.preheader,
        cta_label=body.cta_label,
        cta_url=body.cta_url,
        mapping=mapping,
    )
    send_email(
        to=to,
        subject="[TEST] " + rendered["subject"],
        html_body=rendered["html"],
        text_body=rendered["text"],
        idempotency_key=f"email-test:{admin.id}:{uuid.uuid4().hex[:10]}",
        user_id=int(admin.id),
        organization_id=_org_id(int(admin.id)),
    )
    return {"ok": True, "to": to}


@router.post("/validate-url")
def admin_email_validate_url(
    kind: str = "link",
    url: str = "",
    admin: User = Depends(require_admin_user),
):
    try:
        if kind == "image":
            out = validate_image_url(url)
        else:
            out = validate_link_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "url": out}


@router.post("/upload-image")
def admin_email_upload_image(
    file: UploadFile = File(...),
    admin: User = Depends(require_admin_user),
):
    from app.services.media_storage import save_public_published_image

    data = file.file.read()
    suffix = os.path.splitext(file.filename or "")[1]
    try:
        saved = save_public_published_image(data=data, suffix=suffix)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    base = (os.getenv("APP_BASE_URL") or "https://seoauto.vn").rstrip("/")
    abs_url = base + str(saved["url"])
    return {"ok": True, "url": abs_url, "path": saved["url"]}
