"""Google Map SEO — báo cáo theo map & thời gian."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.google_map_gbp import (
    GbpMedia,
    GbpPost,
    GbpReportBranding,
    GbpReportSnapshot,
    GbpReviewReplyDraft,
)
from app.services.google_map_gbp_profile_service import _resolve_location

_LOG = logging.getLogger("google_map_gbp.reports")

METRIC_KEYS = (
    "map_score",
    "reviews_new",
    "reviews_replied",
    "views",
    "calls",
    "directions",
    "website_clicks",
    "posts_published",
    "photos_new",
    "issues_fixed",
)

METRIC_LABELS: dict[str, str] = {
    "map_score": "Map Score",
    "reviews_new": "Review mới",
    "reviews_replied": "Review đã phản hồi",
    "views": "Lượt xem",
    "calls": "Lượt gọi điện",
    "directions": "Lượt chỉ đường",
    "website_clicks": "Lượt click website",
    "posts_published": "Bài đăng đã đăng",
    "photos_new": "Ảnh mới",
    "issues_fixed": "Lỗi đã sửa",
}

VALID_PERIODS = ("7d", "30d", "90d", "6m")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _seed(user_id: int, location_key: str, salt: str = "") -> int:
    raw = f"{user_id}:{location_key}:{salt}"
    return int(hashlib.sha256(raw.encode()).hexdigest()[:8], 16)


def _period_config(period: str) -> tuple[str, int, timedelta]:
    p = (period or "30d").strip().lower()
    if p not in VALID_PERIODS:
        p = "30d"
    if p == "7d":
        return p, 7, timedelta(days=1)
    if p == "30d":
        return p, 5, timedelta(days=6)
    if p == "90d":
        return p, 6, timedelta(days=15)
    return p, 6, timedelta(days=30)


def _bucket_labels(period: str, *, end: datetime) -> list[tuple[str, datetime, datetime]]:
    p, n, step = _period_config(period)
    labels: list[tuple[str, datetime, datetime]] = []
    for i in range(n):
        b_end = end - step * (n - 1 - i)
        b_start = b_end - step
        if p == "6m":
            label = f"T{b_end.month}"
        elif p == "7d":
            label = b_end.strftime("%d/%m")
        elif p == "30d":
            label = f"Tuần {i + 1}"
        else:
            label = f"Kỳ {i + 1}"
        labels.append((label, b_start, b_end))
    return labels


def _demo_metrics(user_id: int, location_key: str, bucket_idx: int, base: dict[str, int]) -> dict[str, int]:
    s = _seed(user_id, location_key, str(bucket_idx))
    growth = 1.0 + bucket_idx * 0.08 + (s % 7) * 0.01
    return {
        "map_score": min(100, base.get("map_score", 50) + bucket_idx * 3 + (s % 5)),
        "reviews_new": max(0, int((3 + s % 6) * growth)),
        "reviews_replied": max(0, int((2 + s % 4) * growth)),
        "views": max(10, int(base.get("views", 200) * 0.04 * growth)),
        "calls": max(0, int(base.get("calls", 10) * 0.05 * growth)),
        "directions": max(0, int(base.get("directions", 15) * 0.05 * growth)),
        "website_clicks": max(0, int(base.get("website_clicks", 8) * 0.05 * growth)),
        "posts_published": max(0, 1 if bucket_idx % 2 == 0 else 0) + (s % 2),
        "photos_new": max(0, (s % 4) + (1 if bucket_idx % 3 == 0 else 0)),
        "issues_fixed": max(0, (s % 3) + bucket_idx // 2),
    }


def _base_from_location(gbp_row: Any, loc_ui: dict[str, Any]) -> dict[str, int]:
    base = {
        "map_score": 62,
        "views": 1200,
        "calls": 30,
        "directions": 60,
        "website_clicks": 40,
    }
    if gbp_row and gbp_row.audit_snapshot_json:
        try:
            audit = json.loads(gbp_row.audit_snapshot_json)
            if isinstance(audit, dict):
                if audit.get("map_score") is not None:
                    base["map_score"] = int(audit["map_score"])
                ins = audit.get("insights") or {}
                if isinstance(ins, dict):
                    for k in ("views", "calls", "directions", "website_clicks"):
                        if ins.get(k) is not None:
                            base[k] = int(ins[k])
        except Exception:
            pass
    return base


def _count_posts(db: Session, user_id: int, location_key: str, start: datetime, end: datetime) -> int:
    return int(
        db.execute(
            select(func.count())
            .select_from(GbpPost)
            .where(
                GbpPost.user_id == user_id,
                GbpPost.location_key == location_key,
                GbpPost.status == "published",
                GbpPost.published_at.isnot(None),
                GbpPost.published_at >= start,
                GbpPost.published_at < end,
            )
        ).scalar_one()
        or 0
    )


def _count_media(db: Session, user_id: int, location_key: str, start: datetime, end: datetime) -> int:
    return int(
        db.execute(
            select(func.count())
            .select_from(GbpMedia)
            .where(
                GbpMedia.user_id == user_id,
                GbpMedia.location_key == location_key,
                GbpMedia.created_at >= start,
                GbpMedia.created_at < end,
            )
        ).scalar_one()
        or 0
    )


def _count_replies(db: Session, user_id: int, location_key: str, start: datetime, end: datetime) -> int:
    return int(
        db.execute(
            select(func.count())
            .select_from(GbpReviewReplyDraft)
            .where(
                GbpReviewReplyDraft.user_id == user_id,
                GbpReviewReplyDraft.location_key == location_key,
                GbpReviewReplyDraft.updated_at >= start,
                GbpReviewReplyDraft.updated_at < end,
            )
        ).scalar_one()
        or 0
    )


def _sum_metrics(series: list[dict[str, Any]]) -> dict[str, int]:
    totals = {k: 0 for k in METRIC_KEYS}
    for pt in series:
        m = pt.get("metrics") or {}
        for k in METRIC_KEYS:
            if k == "map_score":
                totals[k] = int(m.get(k) or totals[k])
            else:
                totals[k] += int(m.get(k) or 0)
    if series:
        totals["map_score"] = int(series[-1].get("metrics", {}).get("map_score") or totals["map_score"])
    return totals


def _before_after(series: list[dict[str, Any]]) -> dict[str, Any]:
    if not series:
        empty = {k: {"before": 0, "after": 0, "delta": 0, "pct": None} for k in METRIC_KEYS}
        return {"period_label": "—", "metrics": empty}
    first = series[0].get("metrics") or {}
    last = series[-1].get("metrics") or {}
    out: dict[str, Any] = {}
    for k in METRIC_KEYS:
        b = int(first.get(k) or 0)
        a = int(last.get(k) or 0)
        delta = a - b
        pct = round((delta / b) * 100, 1) if b else (100.0 if a else None)
        out[k] = {"before": b, "after": a, "delta": delta, "pct": pct}
    return {
        "period_label": f"{series[0].get('label')} → {series[-1].get('label')}",
        "metrics": out,
    }


def branding_to_dict(row: GbpReportBranding | None) -> dict[str, Any]:
    if not row:
        return {
            "agency_name": "SEOAuto Agency",
            "logo_url": None,
            "accent_color": "#34a853",
            "footer_text": "Báo cáo Google Map SEO — chuẩn bị cho white-label agency.",
            "contact_email": None,
            "white_label_ready": True,
        }
    return {
        "agency_name": row.agency_name or "SEOAuto Agency",
        "logo_url": row.logo_url,
        "accent_color": row.accent_color or "#34a853",
        "footer_text": row.footer_text,
        "contact_email": row.contact_email,
        "white_label_ready": True,
    }


def get_branding(db: Session, user_id: int) -> dict[str, Any]:
    row = db.execute(
        select(GbpReportBranding).where(GbpReportBranding.user_id == user_id)
    ).scalar_one_or_none()
    return branding_to_dict(row)


def save_branding(db: Session, user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    row = db.execute(
        select(GbpReportBranding).where(GbpReportBranding.user_id == user_id)
    ).scalar_one_or_none()
    if not row:
        row = GbpReportBranding(user_id=user_id)
        db.add(row)
    for field in ("agency_name", "logo_url", "accent_color", "footer_text", "contact_email"):
        if field in payload:
            val = payload[field]
            setattr(row, field, str(val).strip() if val else None)
    db.commit()
    db.refresh(row)
    return branding_to_dict(row)


def build_report(
    db: Session,
    user_id: int,
    *,
    location_key: str,
    period: str = "30d",
) -> dict[str, Any]:
    p, _, _ = _period_config(period)
    gbp_row, loc_ui = _resolve_location(db, user_id, location_key)
    end = _now()
    buckets = _bucket_labels(p, end=end)
    base = _base_from_location(gbp_row, loc_ui)

    has_real = bool(gbp_row)
    series: list[dict[str, Any]] = []
    for idx, (label, b_start, b_end) in enumerate(buckets):
        metrics = _demo_metrics(user_id, location_key, idx, base)
        if has_real:
            posts = _count_posts(db, user_id, location_key, b_start, b_end)
            photos = _count_media(db, user_id, location_key, b_start, b_end)
            replies = _count_replies(db, user_id, location_key, b_start, b_end)
            if posts:
                metrics["posts_published"] = posts
            if photos:
                metrics["photos_new"] = photos
            if replies:
                metrics["reviews_replied"] = replies
        series.append(
            {
                "label": label,
                "start": _iso(b_start),
                "end": _iso(b_end),
                "metrics": metrics,
            }
        )

    totals = _sum_metrics(series)
    comparison = _before_after(series)
    source = "mixed" if has_real else "demo"

    location_name = loc_ui.get("name") or location_key
    if not loc_ui and location_key.startswith("loc"):
        location_name = f"Địa điểm demo ({location_key})"

    branding = get_branding(db, user_id)

    return {
        "source": source,
        "source_label": "Dữ liệu thật + mẫu" if source == "mixed" else "Dữ liệu mẫu (demo)",
        "period": p,
        "generated_at": _iso(end),
        "location_key": location_key,
        "location": {
            "name": location_name,
            "address": loc_ui.get("address") or "",
            "category": loc_ui.get("category") or "",
        },
        "branding": branding,
        "totals": totals,
        "comparison": comparison,
        "series": series,
        "chart_metrics": ["views", "calls", "directions", "website_clicks"],
    }


def export_report_csv(report: dict[str, Any]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    loc = report.get("location") or {}
    writer.writerow(["Báo cáo Google Map SEO"])
    writer.writerow(["Địa điểm", loc.get("name", "")])
    writer.writerow(["Kỳ báo cáo", report.get("period", "")])
    writer.writerow(["Ngày tạo", report.get("generated_at", "")])
    writer.writerow([])
    writer.writerow(["Chỉ số", "Tổng kỳ"])
    totals = report.get("totals") or {}
    for k in METRIC_KEYS:
        writer.writerow([METRIC_LABELS[k], totals.get(k, 0)])
    writer.writerow([])
    writer.writerow(["Trước / Sau tối ưu"])
    comp = (report.get("comparison") or {}).get("metrics") or {}
    writer.writerow(["Chỉ số", "Trước", "Sau", "Thay đổi", "%"])
    for k in METRIC_KEYS:
        c = comp.get(k) or {}
        writer.writerow([
            METRIC_LABELS[k],
            c.get("before", 0),
            c.get("after", 0),
            c.get("delta", 0),
            c.get("pct") if c.get("pct") is not None else "",
        ])
    writer.writerow([])
    writer.writerow(["Chi tiết theo thời gian"])
    header = ["Kỳ"] + [METRIC_LABELS[k] for k in METRIC_KEYS]
    writer.writerow(header)
    for pt in report.get("series") or []:
        m = pt.get("metrics") or {}
        writer.writerow([pt.get("label", "")] + [m.get(k, 0) for k in METRIC_KEYS])
    return out.getvalue()


def export_report_pdf(report: dict[str, Any]) -> bytes:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise RuntimeError("Missing dependency: reportlab") from exc

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 40
    branding = report.get("branding") or {}
    loc = report.get("location") or {}
    accent = branding.get("accent_color") or "#34a853"

    def line(text: str, bold: bool = False, size: int = 10) -> None:
        nonlocal y
        if y < 50:
            pdf.showPage()
            y = height - 40
        pdf.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        for chunk in [text[i : i + 95] for i in range(0, len(text), 95)]:
            if y < 50:
                pdf.showPage()
                y = height - 40
                pdf.setFont("Helvetica-Bold" if bold else "Helvetica", size)
            pdf.drawString(40, y, chunk)
            y -= 14

    line(branding.get("agency_name") or "SEOAuto Agency", bold=True, size=16)
    line("Bao cao Google Map SEO", bold=True, size=12)
    y -= 4
    line(f"Dia diem: {loc.get('name', '')}")
    if loc.get("address"):
        line(f"Dia chi: {loc.get('address', '')}")
    line(f"Ky: {report.get('period', '')} | Tao luc: {report.get('generated_at', '')}")
    line(f"Nguon: {report.get('source_label', '')}")
    y -= 8
    line("Tong ket ky", bold=True, size=11)
    totals = report.get("totals") or {}
    for k in METRIC_KEYS:
        line(f"- {METRIC_LABELS[k]}: {totals.get(k, 0)}")
    y -= 8
    line("Truoc / Sau toi uu", bold=True, size=11)
    comp = (report.get("comparison") or {}).get("metrics") or {}
    for k in METRIC_KEYS:
        c = comp.get(k) or {}
        pct = c.get("pct")
        pct_s = f" ({pct:+.1f}%)" if pct is not None else ""
        line(
            f"- {METRIC_LABELS[k]}: {c.get('before', 0)} -> {c.get('after', 0)}"
            f" ({c.get('delta', 0):+d}{pct_s})"
        )
    y -= 8
    line("Chi tiet theo thoi gian", bold=True, size=11)
    for pt in report.get("series") or []:
        m = pt.get("metrics") or {}
        line(
            f"{pt.get('label', '')}: views={m.get('views', 0)}, calls={m.get('calls', 0)}, "
            f"score={m.get('map_score', 0)}"
        )
    if branding.get("footer_text"):
        y -= 10
        line(str(branding["footer_text"]))
    if branding.get("contact_email"):
        line(f"Lien he: {branding['contact_email']}")
    line(f"Mau sac agency (white-label): {accent}", size=8)
    pdf.save()
    buffer.seek(0)
    return buffer.getvalue()
