"""Email Automation + Email Marketing engine.

Builds subject/body with placeholders and tracking pixel/links.
"""

from __future__ import annotations

import html
import os
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models.email_automation_marketing import (
    EmailAutomationTemplate,
    EmailMarketingCampaign,
    EmailSend,
)
from app.services.email_html_sanitize import (
    html_to_text,
    sanitize_email_html,
    unsubscribe_footer_html,
    unsubscribe_footer_text,
    validate_link_url,
)


def _app_base() -> str:
    return (os.getenv("APP_BASE_URL") or "https://seoauto.vn").rstrip("/")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _render_placeholders(template: str, mapping: dict[str, str]) -> str:
    raw = str(template or "")
    for k, v in mapping.items():
        raw = raw.replace(f"{{{{{k}}}}}", str(v or ""))
    return raw


def _fmt_expiry(d: date | datetime | None) -> str:
    if d is None:
        return ""
    if isinstance(d, datetime):
        d = d.date()
    return d.isoformat()


def _tracking_pixel(event_token: str) -> str:
    base = _app_base()
    url = f"{base}/api/email/track/open?token={event_token}"
    return (
        f'<img src="{html.escape(url)}" width="1" height="1" style="display:none" alt=""/>'
    )


def _tracking_click_url(event_token: str) -> str:
    base = _app_base()
    return f"{base}/api/email/track/click?token={event_token}"


def _unsubscribe_url(unsub_token: str) -> str:
    base = _app_base()
    return f"{base}/api/email/unsubscribe?token={unsub_token}"


def _append_cta_button(html_body: str, *, label: str, href: str) -> str:
    safe_label = html.escape(label or "CTA")
    try:
        safe_href = html.escape(validate_link_url(href))
    except ValueError:
        safe_href = html.escape(href or "#")
    btn = (
        '<p style="margin:18px 0;">'
        f'<a href="{safe_href}" '
        'style="display:inline-block;padding:10px 16px;background:#2563eb;color:#fff;'
        'text-decoration:none;border-radius:8px;font-weight:600;">'
        f"{safe_label}"
        "</a>"
        "</p>"
    )
    return (html_body or "").strip() + btn


def _credit_balance_for(db: Session, user_id: int | None) -> str:
    if not user_id:
        return "0"
    try:
        from app.models.user import User

        row = db.get(User, int(user_id))
        if row is None:
            return "0"
        return str(int(getattr(row, "credit_balance", 0) or 0))
    except Exception:
        return "0"


def _preheader_hidden(text: str) -> str:
    val = html.escape((text or "").strip()[:180])
    if not val:
        return ""
    return (
        f'<span style="display:none!important;visibility:hidden;opacity:0;height:0;width:0;">'
        f"{val}</span>"
    )


def placeholder_mapping_for_outbox(db: Session, outbox: EmailSend) -> dict[str, str]:
    now = _utc_now()
    base = _app_base()
    click_url = _tracking_click_url(outbox.event_token)
    return {
        "name": outbox.recipient_name or "",
        "email": outbox.recipient_email or "",
        "plan": outbox.plan_name or "",
        "expiry_date": _fmt_expiry(outbox.expiry_date),
        "credit_balance": _credit_balance_for(db, outbox.recipient_user_id),
        "discount_code": outbox.discount_code or "",
        "unsubscribe_url": _unsubscribe_url(outbox.unsub_token) if outbox.unsub_token else "",
        "cta_url": click_url,
        "app_base": base,
        "now": now.isoformat(),
    }


def preview_mapping(
    *,
    name: str = "Nguyễn Văn A",
    email: str = "demo@seoauto.vn",
    plan: str = "Pro",
    expiry_date: str = "2026-12-31",
    credit_balance: str = "120",
    discount_code: str = "SEO10",
    cta_url: str = "https://seoauto.vn/account-billing",
) -> dict[str, str]:
    return {
        "name": name,
        "email": email,
        "plan": plan,
        "expiry_date": expiry_date,
        "credit_balance": credit_balance,
        "discount_code": discount_code,
        "cta_url": cta_url,
        "unsubscribe_url": f"{_app_base()}/api/email/unsubscribe?token=preview",
        "app_base": _app_base(),
        "now": _utc_now().isoformat(),
    }


def render_email_preview(
    *,
    subject: str,
    html_body: str,
    text_body: str | None,
    preheader: str | None = None,
    cta_label: str | None = None,
    cta_url: str | None = None,
    mapping: dict[str, str] | None = None,
) -> dict[str, str]:
    mapping = mapping or preview_mapping()
    subj = _render_placeholders(subject, mapping).strip() or "SEOAuto"
    body = sanitize_email_html(_render_placeholders(html_body, mapping))
    if preheader:
        body = _preheader_hidden(_render_placeholders(preheader, mapping)) + body
    if cta_label:
        href = mapping.get("cta_url") or cta_url or "#"
        if "display:inline-block;padding:" not in body:
            body = _append_cta_button(body, label=cta_label, href=href)
    unsub = mapping.get("unsubscribe_url") or ""
    if unsub and "unsubscribe" not in body.lower() and "huỷ đăng ký" not in body.lower():
        body += unsubscribe_footer_html(unsub)
    text = _render_placeholders(text_body or "", mapping).strip() or html_to_text(body)
    if unsub:
        text += unsubscribe_footer_text(unsub)
    return {"subject": subj, "html": body, "text": text, "preheader": _render_placeholders(preheader or "", mapping)}


def build_outbox_email_html(
    db: Session,
    outbox: EmailSend,
) -> dict[str, str]:
    """Return {subject, html, text} for the given outbox."""
    mapping = placeholder_mapping_for_outbox(db, outbox)
    event_token = outbox.event_token
    click_url = mapping["cta_url"]
    pixel = _tracking_pixel(event_token)

    if outbox.automation_email_type:
        tpl = (
            db.query(EmailAutomationTemplate)
            .filter(
                EmailAutomationTemplate.owner_user_id == int(outbox.owner_user_id),
                EmailAutomationTemplate.email_type == str(outbox.automation_email_type),
            )
            .one_or_none()
        )
        if tpl is None:
            raise RuntimeError("missing_automation_template")

        subject = _render_placeholders(tpl.subject_template, mapping).strip() or "Thông báo SEOAuto"
        html_body = sanitize_email_html(_render_placeholders(tpl.html_body_template, mapping))
        if getattr(tpl, "preheader_template", None):
            html_body = _preheader_hidden(_render_placeholders(tpl.preheader_template, mapping)) + html_body
        html_body = _append_cta_button(html_body, label="Gia hạn ngay", href=click_url)
        unsub = mapping.get("unsubscribe_url") or _unsubscribe_url(outbox.unsub_token or "")
        if outbox.unsub_token:
            html_body += unsubscribe_footer_html(unsub)
        html_body = html_body + pixel
        text_tpl = tpl.text_body_template or ""
        text_body = _render_placeholders(text_tpl, mapping).strip()
        if not text_body:
            text_body = f"{mapping.get('name')} — {mapping.get('plan')} (hết hạn {mapping.get('expiry_date')})"
        text_body = text_body + f"\n\n{click_url}\n"
        if outbox.unsub_token:
            text_body += unsubscribe_footer_text(unsub)
        return {"subject": subject, "html": html_body, "text": text_body}

    campaign = db.get(EmailMarketingCampaign, outbox.campaign_id) if outbox.campaign_id else None
    if campaign is None:
        raise RuntimeError("missing_marketing_campaign")

    subject = _render_placeholders(campaign.subject, mapping).strip() or "Chương trình email SEOAuto"
    html_body = sanitize_email_html(_render_placeholders(campaign.html_body, mapping))
    if getattr(campaign, "preheader", None):
        html_body = _preheader_hidden(_render_placeholders(campaign.preheader, mapping)) + html_body

    html_body = _append_cta_button(
        html_body,
        label=campaign.cta_label or "Mở ngay",
        href=click_url,
    )

    if outbox.unsub_token:
        html_body += unsubscribe_footer_html(_unsubscribe_url(outbox.unsub_token))
    html_body = html_body + pixel

    text_tpl = campaign.text_body or ""
    text_body = _render_placeholders(text_tpl, mapping).strip()
    if not text_body:
        text_body = html_to_text(html_body) or subject
    text_body = text_body + f"\n\n{click_url}"
    if outbox.unsub_token:
        text_body += unsubscribe_footer_text(_unsubscribe_url(outbox.unsub_token))
    return {"subject": subject, "html": html_body, "text": text_body}


def build_click_target_url(db: Session, outbox: EmailSend) -> str:
    if outbox.automation_email_type:
        return f"{_app_base()}/account-billing?tab=plans"
    if outbox.campaign_id:
        camp = db.get(EmailMarketingCampaign, outbox.campaign_id)
        if camp is None:
            return _app_base() + "/"
        raw = str(camp.cta_url or _app_base() + "/")
        try:
            return validate_link_url(raw)
        except ValueError:
            return _app_base() + "/"
    return _app_base() + "/"


def _user_name_from_email(email: str) -> str:
    raw = str(email or "").strip()
    if "@" in raw:
        raw = raw.split("@", 1)[0]
    raw = raw.replace(".", " ").replace("_", " ").replace("-", " ")
    raw = " ".join(x for x in raw.split() if x)
    return raw[:120]


def list_segment_recipients(
    db: Session,
    *,
    segment_kind: str = "active",
    segment_plan_id: int | None = None,
    q: str | None = None,
    limit: int = 500,
) -> list[dict]:
    """Return recipients for marketing segment: user_id, email, name, plan_name, expiry_date, credit_balance."""
    from sqlalchemy import text

    kind = str(segment_kind or "active").strip().lower()
    now = _utc_now()
    where_clause = "u.status='active'"
    params: dict = {"lim": max(1, min(int(limit), 1000))}

    if kind == "all":
        where_clause = "u.status='active'"
    elif kind == "trial":
        where_clause = "s.status='trialing' AND s.current_period_end > :now"
        params["now"] = now
    elif kind == "active":
        where_clause = "s.status='active' AND s.current_period_end > :now"
        params["now"] = now
    elif kind == "expired":
        where_clause = "s.status='expired'"
    elif kind == "low_credit":
        where_clause = "u.status='active' AND COALESCE(u.credit_balance,0) < :low_credit"
        params["low_credit"] = 50
    elif kind == "by_plan":
        where_clause = (
            "s.plan_id=:pid AND s.status IN ('trialing','active') AND s.current_period_end > :now"
        )
        params["pid"] = int(segment_plan_id or 0)
        params["now"] = now
    else:
        where_clause = "s.status='active' AND s.current_period_end > :now"
        params["now"] = now

    needle = str(q or "").strip().lower()
    if needle:
        where_clause += " AND lower(u.email) LIKE :q"
        params["q"] = f"%{needle[:120]}%"

    sql = (
        "SELECT u.id as user_id, u.email as email, "
        "p.name as plan_name, s.current_period_end as expiry_date, "
        "COALESCE(u.credit_balance, 0) as credit_balance "
        "FROM users u "
        "JOIN subscriptions s ON s.user_id=u.id "
        "JOIN plans p ON p.id=s.plan_id "
        f"WHERE {where_clause} "
        "ORDER BY s.current_period_end DESC "
        "LIMIT :lim"
    )
    rows = db.execute(text(sql), params).fetchall()
    seen: set[int] = set()
    out: list[dict] = []
    for r in rows:
        uid = int(r[0])
        if uid in seen:
            continue
        seen.add(uid)
        email = str(r[1] or "").strip().lower()
        if not email or "@" not in email:
            continue
        plan_name = str(r[2] or "") or "SEOAuto plan"
        exp_dt = r[3]
        if isinstance(exp_dt, datetime):
            exp_date = exp_dt.date()
            exp_iso = exp_dt.isoformat()
        else:
            exp_date = None
            exp_iso = None
        out.append(
            {
                "user_id": uid,
                "email": email,
                "name": _user_name_from_email(email),
                "plan_name": plan_name,
                "expiry_date": exp_date.isoformat() if exp_date else exp_iso,
                "expiry_date_obj": exp_date,
                "credit_balance": int(r[4] or 0),
            }
        )
    return out
