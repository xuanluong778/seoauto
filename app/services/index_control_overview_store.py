"""Index Control — tổng quan từ lịch sử check + log IndexNow."""

from __future__ import annotations

from typing import Any

from sqlalchemy import case, desc, func, select
from sqlalchemy.orm import Session

from app.models.index_control import IndexControlCheckItem, IndexNowSubmit, IndexNowSubmitLog
from app.services.index_control_history_store import _item_to_dict
from app.services.user_scope import is_admin_role

_SEVERITY_ORDER = case(
    (IndexControlCheckItem.severity == "critical", 0),
    (IndexControlCheckItem.severity == "high", 1),
    (IndexControlCheckItem.severity == "medium", 2),
    else_=3,
)


def _history_filters(
    q,
    *,
    user_id: int,
    role: str | None,
    domain: str | None,
    url_type: str | None,
):
    if not is_admin_role(role):
        q = q.where(IndexControlCheckItem.user_id == int(user_id))
    if domain:
        q = q.where(IndexControlCheckItem.domain == domain.strip().lower())
    if url_type:
        ut = url_type.strip().lower()
        if ut in ("main_site", "website"):
            q = q.where(IndexControlCheckItem.url_type.in_(("website", "main_site")))
        else:
            q = q.where(IndexControlCheckItem.url_type == ut)
    return q


def _indexnow_base(*, user_id: int, role: str | None, domain: str | None):
    q = (
        select(IndexNowSubmitLog)
        .join(IndexNowSubmit, IndexNowSubmitLog.submit_id == IndexNowSubmit.id)
        .where(IndexNowSubmitLog.send_status == "sent")
    )
    if not is_admin_role(role):
        q = q.where(IndexNowSubmitLog.user_id == int(user_id))
    if domain:
        q = q.where(IndexNowSubmit.domain == domain.strip().lower())
    return q


def get_overview(
    db: Session,
    *,
    user_id: int,
    role: str | None,
    domain: str | None = None,
    url_type: str | None = None,
    urgent_limit: int = 50,
) -> dict[str, Any]:
    stats_q = select(
        func.count(IndexControlCheckItem.id).label("total"),
        func.sum(case((IndexControlCheckItem.indexability == "indexable", 1), else_=0)).label("indexable"),
        func.sum(case((IndexControlCheckItem.indexability == "warning", 1), else_=0)).label("warning"),
        func.sum(case((IndexControlCheckItem.indexability == "blocked", 1), else_=0)).label("blocked"),
        func.sum(case((IndexControlCheckItem.indexability == "error", 1), else_=0)).label("error"),
    )
    stats_q = _history_filters(
        stats_q, user_id=user_id, role=role, domain=domain, url_type=url_type
    )
    stats_row = db.execute(stats_q).one()

    def _int(val: Any) -> int:
        return int(val or 0)

    indexnow_sent = db.scalar(select(func.count()).select_from(_indexnow_base(
        user_id=user_id, role=role, domain=domain
    ).subquery())) or 0

    domains_q = select(IndexControlCheckItem.domain).distinct()
    domains_q = _history_filters(
        domains_q, user_id=user_id, role=role, domain=None, url_type=url_type
    )
    domains_q = domains_q.where(IndexControlCheckItem.domain.isnot(None)).where(IndexControlCheckItem.domain != "")
    domain_rows = db.scalars(domains_q).all()
    domains = sorted({str(d).strip().lower() for d in domain_rows if d})

    urgent_q = _history_filters(
        select(IndexControlCheckItem),
        user_id=user_id,
        role=role,
        domain=domain,
        url_type=url_type,
    ).where(
        IndexControlCheckItem.indexability != "indexable"
    ).order_by(
        _SEVERITY_ORDER,
        desc(IndexControlCheckItem.created_at),
    ).limit(min(max(1, urgent_limit), 100))

    urgent_rows = db.scalars(urgent_q).all()
    urgent_items = [_item_to_dict(r) for r in urgent_rows]

    return {
        "ok": True,
        "is_admin": is_admin_role(role),
        "stats": {
            "total_checked": _int(stats_row.total),
            "indexable": _int(stats_row.indexable),
            "warning": _int(stats_row.warning),
            "blocked": _int(stats_row.blocked),
            "error": _int(stats_row.error),
            "indexnow_sent": _int(indexnow_sent),
        },
        "domains": domains,
        "urgent_items": urgent_items,
        "urgent_count": len(urgent_items),
    }
