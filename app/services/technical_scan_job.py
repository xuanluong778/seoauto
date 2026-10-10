"""Background technical scan jobs — avoid Cloudflare/nginx 504 on long crawls."""

from __future__ import annotations

import logging
import os
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db import SessionLocal, ensure_db_alive, release_db_before_long_io
from app.models.keyword_cluster_job import KeywordClusterJob
from app.models.user import User
from app.services.job_store import (
    create_job,
    fail_job,
    finish_job,
    get_job_for_user,
    update_job,
)

_LOG = logging.getLogger(__name__)

JOB_TYPE = "technical_analyze"
TECHNICAL_SCAN_BUDGET_SECONDS = int(os.getenv("TECHNICAL_SCAN_BUDGET_SECONDS", "540") or 540)


def _budget_seconds() -> int:
    try:
        return max(60, min(840, int(os.getenv("TECHNICAL_SCAN_BUDGET_SECONDS", str(TECHNICAL_SCAN_BUDGET_SECONDS)))))
    except (TypeError, ValueError):
        return 540


def find_technical_job_by_idempotency(
    user_id: int,
    idempotency_key: str,
    *,
    max_age_seconds: int = 1800,
) -> Any:
    """Reuse QUEUED/RUNNING/SUCCESS job for the same user + idempotency key."""
    uid = int(user_id or 0)
    key = str(idempotency_key or "").strip()
    if uid <= 0 or not key:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(60, int(max_age_seconds)))
    db = SessionLocal()
    try:
        rows = (
            db.query(KeywordClusterJob)
            .filter(KeywordClusterJob.user_id == uid)
            .filter(KeywordClusterJob.job_type == JOB_TYPE)
            .filter(KeywordClusterJob.state.in_(("QUEUED", "PENDING", "RUNNING", "SUCCESS")))
            .filter(KeywordClusterJob.created_at >= cutoff)
            .order_by(KeywordClusterJob.created_at.desc())
            .limit(40)
            .all()
        )
        for row in rows or []:
            from app.services.job_store import _row_to_state

            st = _row_to_state(row)
            payload = st.payload if isinstance(st.payload, dict) else {}
            if str(payload.get("idempotency_key") or "").strip() == key:
                return st
        return None
    finally:
        db.close()


def _finalize_credits(
    db: Session,
    *,
    user_id: int,
    reservation_id: int | None,
    reserved_amount: int,
    feature: str,
    commit: bool,
    reason: str,
    url: str,
    idempotency_key: str | None,
) -> None:
    from app.services.credits import commit_reservation, release_reservation
    from app.services.plan_quota_service import record_quota_usage
    from app.services.usage_tracking_service import record_successful_usage

    if not reservation_id:
        return
    if commit:
        commit_reservation(db, reservation_id=int(reservation_id), user_id=int(user_id))
        record_quota_usage(
            db,
            int(user_id),
            feature,
            quantity=1,
            credits_used=int(reserved_amount or 0),
        )
        record_successful_usage(
            db,
            int(user_id),
            feature,
            quantity=1,
            credits_used=int(reserved_amount or 0),
            metadata={"url": (url or "")[:200]},
            idempotency_key=idempotency_key,
        )
    else:
        release_reservation(
            db,
            reservation_id=int(reservation_id),
            user_id=int(user_id),
            reason=reason,
        )


def _user_facing_job_error(exc: BaseException) -> str:
    """Avoid dumping SQLAlchemy stack traces into the UI."""
    msg = str(exc or "")
    low = msg.lower()
    if "server closed the connection" in low or "connection unexpectedly" in low:
        return (
            "Kết nối dữ liệu bị gián đoạn sau khi crawl xong (PgBouncer/DB). "
            "Vui lòng bấm Thử lại — kết quả crawl thường chạy lại nhanh hơn."
        )
    if "statement timeout" in low or "querycanceled" in low:
        return "Thao tác lưu kết quả quét bị timeout. Vui lòng thử lại."
    if "lock timeout" in low or "locknotavailable" in low:
        return "Hệ thống đang bận (khóa DB). Vui lòng thử lại sau vài giây."
    cleaned = msg.strip()[:500]
    return cleaned or "Quét technical thất bại."


def run_technical_scan_job(job_id: str, payload: dict[str, Any]) -> None:
    from app.services.analyzer import analyze_technical_seo
    from app.services.audit_store import save_technical_audit
    from app.services.cost_control import CostGateRequest, ExternalApiProvider, cost_gate_session
    from app.services.plan_quota_registry import feature_key_for

    user_id = int(payload.get("user_id") or 0)
    url = str(payload.get("url") or "").strip()
    reservation_id = payload.get("reservation_id")
    try:
        reservation_id = int(reservation_id) if reservation_id else None
    except (TypeError, ValueError):
        reservation_id = None
    reserved_amount = int(payload.get("reserved_amount") or 0)
    feature = str(payload.get("feature_key") or feature_key_for("technical_audit"))
    idem_key = str(payload.get("idempotency_key") or "").strip() or None

    def hook(pct: int, msg: str) -> None:
        update_job(job_id, state="RUNNING", progress=int(pct), message=str(msg)[:500])

    db = SessionLocal()
    try:
        update_job(job_id, state="RUNNING", progress=2, message="Bắt đầu quét technical…")
        user = db.query(User).filter(User.id == user_id).one_or_none()
        if not user:
            fail_job(job_id, error="Không tìm thấy tài khoản.")
            _finalize_credits(
                db,
                user_id=user_id,
                reservation_id=reservation_id,
                reserved_amount=reserved_amount,
                feature=feature,
                commit=False,
                reason="user_missing",
                url=url,
                idempotency_key=idem_key,
            )
            db.commit()
            return

        deadline = time.monotonic() + _budget_seconds()
        gate_req = CostGateRequest(
            db=db,
            user=user,
            provider=ExternalApiProvider.CRAWL,
            action="technical_analyze",
            credit_cost=0,
            feature_key=feature,
            quota_units=1,
            skip_credit_check=True,
            single_flight_key=f"technical_analyze_job:{user_id}",
        )
        with cost_gate_session(gate_req):
            # Long crawl must not hold a PgBouncer transaction open.
            release_db_before_long_io(db)
            result = analyze_technical_seo(
                url,
                max_pages=int(payload.get("max_pages") or 25),
                user_id=user_id,
                use_gsc=bool(payload.get("use_gsc")),
                gsc_property=payload.get("gsc_property"),
                gsc_date_range=str(payload.get("gsc_date_range") or "28d"),
                gsc_start_date=payload.get("gsc_start_date"),
                gsc_end_date=payload.get("gsc_end_date"),
                url_inspection_limit=int(payload.get("url_inspection_limit") or 10),
                deadline_monotonic=deadline,
                progress_hook=hook,
            )

        result_dict = result.model_dump()
        try:
            from app.services.technical_output_normalizer import build_saas_api_extensions

            result_dict.update(build_saas_api_extensions(result_dict))
        except Exception as exc:
            _LOG.warning("SaaS normalizer failed (job continues): %s", exc, exc_info=True)
            from app.services.technical_output_normalizer import empty_saas_api_extensions

            result_dict.update(empty_saas_api_extensions())

        def _persist_result(*, charge: bool) -> None:
            ensure_db_alive(db)
            pages = int(result_dict.get("pages_scanned") or 0)
            if pages <= 0 and not result_dict.get("partial_data"):
                _finalize_credits(
                    db,
                    user_id=user_id,
                    reservation_id=reservation_id,
                    reserved_amount=reserved_amount,
                    feature=feature,
                    commit=False,
                    reason="empty_crawl",
                    url=url,
                    idempotency_key=idem_key,
                )
                db.commit()
                fail_job(job_id, error="Không crawl được trang nào. Thử lại hoặc kiểm tra URL.")
                return

            audit_id = save_technical_audit(
                user_id=user_id,
                source_url=url,
                result=result_dict,
                idempotency_key=idem_key,
            )
            result_dict["audit_id"] = audit_id
            _finalize_credits(
                db,
                user_id=user_id,
                reservation_id=reservation_id,
                reserved_amount=reserved_amount,
                feature=feature,
                commit=bool(charge),
                reason="ok" if charge else "empty_crawl",
                url=url,
                idempotency_key=idem_key,
            )
            db.commit()
            finish_job(job_id, result=result_dict)

        try:
            _persist_result(charge=True)
        except OperationalError:
            _LOG.warning("technical scan persist OperationalError — reconnect once job_id=%s", job_id)
            try:
                ensure_db_alive(db)
                _persist_result(charge=True)
            except Exception as exc2:
                raise exc2
    except Exception as exc:
        _LOG.exception("technical scan job failed job_id=%s", job_id)
        try:
            ensure_db_alive(db)
            _finalize_credits(
                db,
                user_id=user_id,
                reservation_id=reservation_id,
                reserved_amount=reserved_amount,
                feature=feature,
                commit=False,
                reason="job_failed",
                url=url,
                idempotency_key=idem_key,
            )
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
        fail_job(job_id, error=_user_facing_job_error(exc))
    finally:
        db.close()


def start_technical_scan_thread(job_id: str, payload: dict[str, Any]) -> None:
    """
    Enqueue technical scan on Celery (default). Falls back to in-process thread
    when TECHNICAL_SCAN_CELERY=0 or broker enqueue fails (TECHNICAL_SCAN_THREAD_FALLBACK=1).
    """
    from app.workers.technical_scan_tasks import (
        enqueue_technical_scan,
        technical_scan_celery_enabled,
        technical_scan_thread_fallback_enabled,
    )

    if technical_scan_celery_enabled():
        try:
            enqueue_technical_scan(job_id, payload)
            return
        except Exception:
            _LOG.exception("technical_scan_celery_enqueue_failed job_id=%s", job_id)
            if not technical_scan_thread_fallback_enabled():
                fail_job(job_id, error="Không enqueue được Celery technical scan.")
                return

    threading.Thread(
        target=run_technical_scan_job,
        args=(job_id, payload),
        daemon=True,
        name=f"tech-scan-{job_id[:8]}",
    ).start()


def poll_technical_job(job_id: str, user_id: int) -> dict[str, Any] | None:
    st = get_job_for_user(job_id, user_id=user_id)
    if not st:
        return None
    out: dict[str, Any] = {
        "job_id": st.job_id,
        "state": st.state,
        "progress": st.progress,
        "message": st.message,
    }
    if st.state == "SUCCESS" and st.result is not None:
        out["result"] = st.result
    if st.state == "ERROR":
        out["error"] = st.error or "Quét technical thất bại."
    return out
