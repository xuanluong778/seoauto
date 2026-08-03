from pathlib import Path
import csv
import io
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.models.user import User
from app.services.api_payload_optimizer import (
    find_audit_issue,
    paginate_list,
    shape_audit_response,
)
from app.services.audit_store import (
    delete_audit,
    get_audit_for_user,
    get_latest_audit,
    list_audits,
    list_mine_recent_by_domain,
)
from app.services.auth import get_current_user
from app.services.user_data_paths import user_action_plan_deploy_file, user_action_plan_notes_file
from app.seo_pipeline.constants import CHECKLIST_TITLE_VI
from app.services.report_builder import (
    ACTION_PLAN_CSV_COLUMNS,
    GROUP_REFERENCES,
    GROUP_SOLUTIONS_VI,
    SEVERITY_LABEL_VI,
    STATUS_LABEL_VI,
    audit_issues_summary,
    build_action_plan_rows,
    build_audit_action_plan_rows,
    build_lean_action_plan,
    build_seo_report_from_file,
    load_deploy_links_map,
    load_notes_map,
    parse_deploy_links_by_priority,
    parse_notes_by_priority,
    read_gsc_indexing_counts_raw,
    resolve_audit_issues_for_export,
    save_deploy_links_map,
    save_gsc_indexing_counts_raw,
    save_notes_map,
)

router = APIRouter(tags=["report"])
templates = Jinja2Templates(directory="templates")
# Neo theo thư mục dự án (tránh cwd khác khiến không đọc được checklist mới)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_REPORT_FILE = _PROJECT_ROOT / "Technical-SEO.txt"
BUNDLED_TECHNICAL_CHECKLIST = _PROJECT_ROOT / "data" / "Technical-SEO.txt"
OKE_TECHNICAL_CHECKLIST = _PROJECT_ROOT / "technical-checklist-oke.txt"


def technical_checklist_path() -> Path | None:
    """Ưu tiên `technical-checklist-oke.txt` → `data/Technical-SEO.txt` → `Technical-SEO.txt` ở gốc dự án."""
    if OKE_TECHNICAL_CHECKLIST.is_file():
        return OKE_TECHNICAL_CHECKLIST
    if BUNDLED_TECHNICAL_CHECKLIST.is_file():
        return BUNDLED_TECHNICAL_CHECKLIST
    if DEFAULT_REPORT_FILE.is_file():
        return DEFAULT_REPORT_FILE
    return None


@router.get("/api/gsc-indexing-counts")
def api_get_gsc_indexing_counts(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    """Đọc số liệu GSC theo user — data/users/{id}/gsc_indexing_counts.json."""
    from app.services.user_data_paths import user_gsc_indexing_counts_file

    path = user_gsc_indexing_counts_file(current_user.id)
    if not path.is_file():
        return {}
    try:
        import json

        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


@router.put("/api/gsc-indexing-counts")
def api_put_gsc_indexing_counts(
    payload: dict[str, Any],
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    """Ghi file JSON sau khi kiểm tra (số nguyên ≥ 0; _meta tùy chọn)."""
    from app.services.report_builder import validate_and_normalize_gsc_indexing_counts
    from app.services.user_data_paths import user_data_dir, user_gsc_indexing_counts_file

    try:
        normalized = validate_and_normalize_gsc_indexing_counts(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    import json

    dest = user_gsc_indexing_counts_file(current_user.id)
    user_data_dir(current_user.id)
    dest.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True}


@router.get("/api/audit/latest")
def api_audit_latest(current_user: User = Depends(get_current_user)) -> JSONResponse:
    run = get_latest_audit(user_id=current_user.id)
    if not run:
        return JSONResponse(
            status_code=404,
            content={"detail": "Chưa có kết quả quét Technical SEO nào. Chạy «Kiểm tra Technical» tại /tool."},
        )
    return JSONResponse(content=run)


@router.get("/api/audit/runs")
def api_audit_runs(
    limit: int = Query(default=20, ge=1, le=40),
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    return JSONResponse(content={"runs": list_audits(limit=limit, user_id=current_user.id)})


_AUDIT_ISSUE_CSV_FIELDS = [
    "Điểm sức khỏe (site)",
    "Penalty tổng hợp",
    "Issue Cao/TB/Thấp",
    "Nhóm checklist",
    "Mức",
    "Loại",
    "Mô tả",
    "URL",
    "Gợi ý sửa (suggested_fix)",
    "Remediation",
    "Độ tin cậy",
    "Giải thích",
    "Loại trang",
]


def _sev_rank(sev: str | None) -> int:
    s = str(sev or "").lower()
    return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(s, 0)


def _collect_issue_urls(issue: dict) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in [str(issue.get("url") or "").strip(), *[
        str(x or "").strip()
        for x in (issue.get("urls") or issue.get("affected_urls") or issue.get("sample_urls") or [])
    ]]:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _group_audit_issues(run: dict) -> list[dict]:
    grouped: dict[str, dict] = {}
    for issue in resolve_audit_issues_for_export(run):
        if not isinstance(issue, dict):
            continue
        t = str(issue.get("type") or "").strip()
        if not t:
            continue
        cur = grouped.get(t)
        if cur is None:
            cur = {
                "type": t,
                "severity": str(issue.get("severity") or "low").lower(),
                "checklist_group": issue.get("checklist_group") or "General",
                "messages": [],
                "urls": [],
                "remediation": issue.get("remediation"),
                "suggested_fix": issue.get("suggested_fix"),
                "explanation": issue.get("explanation"),
                "page_types": [],
                "confidence": issue.get("confidence"),
            }
            grouped[t] = cur
        else:
            if _sev_rank(issue.get("severity")) > _sev_rank(cur.get("severity")):
                cur["severity"] = str(issue.get("severity") or "low").lower()
            if not cur.get("remediation") and issue.get("remediation"):
                cur["remediation"] = issue.get("remediation")
            if not cur.get("suggested_fix") and issue.get("suggested_fix"):
                cur["suggested_fix"] = issue.get("suggested_fix")
            if not cur.get("explanation") and issue.get("explanation"):
                cur["explanation"] = issue.get("explanation")
            try:
                c_old = float(cur.get("confidence")) if cur.get("confidence") is not None else None
            except (TypeError, ValueError):
                c_old = None
            try:
                c_new = float(issue.get("confidence")) if issue.get("confidence") is not None else None
            except (TypeError, ValueError):
                c_new = None
            if c_new is not None and (c_old is None or c_new > c_old):
                cur["confidence"] = c_new

        msg = (issue.get("message") or "").strip()
        if msg and msg not in cur["messages"]:
            cur["messages"].append(msg)
        for u in _collect_issue_urls(issue):
            if u not in cur["urls"]:
                cur["urls"].append(u)
        pt = (issue.get("page_type") or "").strip()
        if pt and pt not in cur["page_types"]:
            cur["page_types"].append(pt)

    out: list[dict] = []
    for _, g in grouped.items():
        msgs = g.get("messages") or []
        if len(msgs) > 1:
            message = msgs[0] + f" (+{len(msgs) - 1} biến thể cùng thuộc tính)"
        else:
            message = msgs[0] if msgs else ""
        out.append(
            {
                "type": g["type"],
                "severity": g.get("severity") or "low",
                "checklist_group": g.get("checklist_group") or "General",
                "message": message,
                "urls": g.get("urls") or [],
                "url": (g.get("urls") or [""])[0] if (g.get("urls") or []) else "",
                "remediation": g.get("remediation"),
                "suggested_fix": g.get("suggested_fix"),
                "explanation": g.get("explanation"),
                "page_type": ", ".join(g.get("page_types") or []),
                "confidence": g.get("confidence"),
            }
        )
    out.sort(key=lambda x: (-_sev_rank(x.get("severity")), str(x.get("type") or "")))
    return out


def _audits_this_month(user_id: int) -> int:
    from datetime import datetime, timezone

    ym = datetime.now(timezone.utc).strftime("%Y-%m")
    return sum(
        1
        for run in list_audits(limit=40, user_id=user_id)
        if str(run.get("at") or "").startswith(ym)
    )


def _build_dashboard_action_items(
    latest_audit: dict | None,
    grouped_issues: list[dict],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if latest_audit:
        for pf in (latest_audit.get("priority_fixes") or [])[:6]:
            if not isinstance(pf, dict):
                continue
            items.append(
                {
                    "title": str(pf.get("title") or pf.get("message") or pf.get("type") or "Ưu tiên sửa"),
                    "detail": str(pf.get("message") or pf.get("problem") or pf.get("explanation") or ""),
                    "fix": str(pf.get("fix") or pf.get("remediation") or pf.get("suggested_fix") or ""),
                    "priority": str(pf.get("priority") or pf.get("severity") or "high").lower(),
                }
            )
    if not items:
        for g in grouped_issues[:5]:
            items.append(
                {
                    "title": str(g.get("type") or "Issue"),
                    "detail": str(g.get("message") or ""),
                    "fix": str(g.get("remediation") or g.get("suggested_fix") or ""),
                    "priority": str(g.get("severity") or "medium").lower(),
                }
            )
    return items


def _build_dashboard_context(
    *,
    current_user: User | None,
    latest_audit: dict | None,
    grouped_issues: list[dict],
) -> dict[str, Any]:
    logged_in = current_user is not None
    uid = int(current_user.id) if current_user else 0
    ts = (latest_audit or {}).get("technical_summary") or {}
    health = ts.get("health_score")
    la = latest_audit or {}
    snapshot: dict[str, Any] | None = None
    if la:
        snapshot = {
            "id": str(la.get("id") or la.get("audit_id") or ""),
            "domain": str(la.get("domain") or ""),
            "source_url": str(la.get("source_url") or ""),
            "at": str(la.get("at") or ""),
            "pages_scanned": int(la.get("pages_scanned") or 0),
            "technical_summary": ts if isinstance(ts, dict) else {},
            "issue_count": int(
                ts.get("total_technical_issues")
                if ts.get("total_technical_issues") is not None
                else len(la.get("issues") or [])
            ),
            "priority_fixes": (la.get("priority_fixes") or [])[:8],
        }
    return {
        "logged_in": logged_in,
        "user_email": str(current_user.email) if current_user and current_user.email else "",
        "recent_audits": list_mine_recent_by_domain(uid, limit=8) if logged_in else [],
        "action_items": _build_dashboard_action_items(latest_audit, grouped_issues),
        "audits_this_month": _audits_this_month(uid) if logged_in else 0,
        "latest_health_score": health if health is not None else None,
        "latest_domain": str(la.get("domain") or ""),
        "latest_issue_count": int(
            ts.get("total_technical_issues")
            if ts.get("total_technical_issues") is not None
            else len(la.get("issues") or [])
        ),
        "latest_audit_id": str(la.get("id") or la.get("audit_id") or ""),
        "latest_audit_snapshot": snapshot,
    }


def _technical_audit_issues_csv(run: dict) -> str:
    out = io.StringIO()
    out.write("\ufeff")
    ts = run.get("technical_summary") or {}
    if not isinstance(ts, dict):
        ts = {}
    hs = ts.get("health_score")
    wp = ts.get("weighted_penalty")
    by = ts.get("issues_by_severity") or {}
    if isinstance(by, dict):
        sev_txt = f"H{by.get('high', 0)}/M{by.get('medium', 0)}/L{by.get('low', 0)}"
    else:
        sev_txt = ""

    hs_cell = "" if hs is None else str(hs)
    wp_cell = "" if wp is None else str(wp)

    writer = csv.DictWriter(out, fieldnames=_AUDIT_ISSUE_CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    issues_raw = _group_audit_issues(run)
    wrote_any = False
    for issue in issues_raw:
        if not isinstance(issue, dict):
            continue
        wrote_any = True
        msg = issue.get("message") or ""
        rem = (issue.get("remediation") or "").strip()
        sug = (issue.get("suggested_fix") or "").strip()
        expl = (issue.get("explanation") or "").strip()
        pt = (issue.get("page_type") or "").strip()
        conf = issue.get("confidence")
        conf_s = ""
        if conf is not None:
            try:
                conf_s = f"{float(conf):.3f}"
            except (TypeError, ValueError):
                conf_s = str(conf)
        writer.writerow(
            {
                "Điểm sức khỏe (site)": hs_cell,
                "Penalty tổng hợp": wp_cell,
                "Issue Cao/TB/Thấp": sev_txt,
                "Nhóm checklist": issue.get("checklist_group") or "",
                "Mức": issue.get("severity") or "",
                "Loại": issue.get("type") or "",
                "Mô tả": msg,
                "URL": issue.get("url") or "",
                "Gợi ý sửa (suggested_fix)": sug,
                "Remediation": rem,
                "Độ tin cậy": conf_s,
                "Giải thích": expl,
                "Loại trang": pt,
            }
        )
    if not wrote_any and (hs_cell or wp_cell or sev_txt):
        writer.writerow(
            {
                "Điểm sức khỏe (site)": hs_cell,
                "Penalty tổng hợp": wp_cell,
                "Issue Cao/TB/Thấp": sev_txt,
                "Nhóm checklist": "",
                "Mức": "",
                "Loại": "_summary_",
                "Mô tả": "Không có dòng issue; chỉ tổng hợp điểm sau quét.",
                "URL": "",
                "Gợi ý sửa (suggested_fix)": "",
                "Remediation": "",
                "Độ tin cậy": "",
                "Giải thích": "",
                "Loại trang": "",
            }
        )
    return out.getvalue()


@router.get("/api/audit/mine")
def api_audit_mine(
    limit: int = Query(8, ge=1, le=20),
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    return JSONResponse(
        content={"items": list_mine_recent_by_domain(current_user.id, limit=limit)},
    )


@router.delete("/api/audit/{audit_id}")
def api_audit_delete(
    audit_id: str,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    if not delete_audit(audit_id, current_user.id):
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy bản quét hoặc bạn không có quyền xóa.",
        )
    return JSONResponse(content={"ok": True})


@router.get("/api/audit/{audit_id}/export.csv")
def api_audit_export_csv(
    audit_id: str,
    current_user: User = Depends(get_current_user),
) -> Response:
    run = get_audit_for_user(audit_id, current_user.id)
    if not run:
        return JSONResponse(status_code=404, content={"detail": "Không tìm thấy bản quét."})
    domain = (run.get("domain") or "audit").replace("/", "-")[:80]
    body = _technical_audit_issues_csv(run)
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="technical-audit-{domain}.csv"',
        },
    )


@router.get("/api/audit/{audit_id}/export.pdf", response_model=None)
def api_audit_export_pdf(
    audit_id: str,
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    run = get_audit_for_user(audit_id, current_user.id)
    if not run:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản quét.")
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="Missing dependency: reportlab") from exc

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    _, height = A4
    y = height - 40
    domain = str(run.get("domain") or "")
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(40, y, "Technical SEO audit")
    y -= 18
    pdf.setFont("Helvetica", 9)
    meta = f"Domain: {domain} | pages: {run.get('pages_scanned', 0)} | at: {run.get('at', '')}"
    for chunk in [meta[i : i + 100] for i in range(0, len(meta), 100)]:
        pdf.drawString(40, y, chunk)
        y -= 12
    ts = run.get("technical_summary") or {}
    if isinstance(ts, dict) and ts.get("health_score") is not None:
        hs = ts.get("health_score")
        wp = ts.get("weighted_penalty")
        score_line = f"Health score: {hs}/100 | weighted_penalty: {wp}"
        for chunk in [score_line[i : i + 100] for i in range(0, len(score_line), 100)]:
            if y < 48:
                pdf.showPage()
                pdf.setFont("Helvetica", 9)
                y = height - 40
            pdf.drawString(40, y, chunk)
            y -= 12
    y -= 8
    pdf.setFont("Helvetica", 8)
    for issue in _group_audit_issues(run):
        if not isinstance(issue, dict):
            continue
        msg = issue.get("message") or ""
        rem = (issue.get("remediation") or "").strip()
        sug = (issue.get("suggested_fix") or "").strip()
        fix = sug or rem
        line = f"[{issue.get('severity', '')}] {issue.get('type', '')}: {msg[:220]}"
        for part in [line[i : i + 110] for i in range(0, len(line), 110)]:
            if y < 48:
                pdf.showPage()
                pdf.setFont("Helvetica", 8)
                y = height - 40
            pdf.drawString(40, y, part)
            y -= 10
        if fix:
            rline = "Goi y sua: " + fix[:500]
            for part in [rline[i : i + 110] for i in range(0, len(rline), 110)]:
                if y < 48:
                    pdf.showPage()
                    pdf.setFont("Helvetica", 8)
                    y = height - 40
                pdf.drawString(40, y, part)
                y -= 10
        expl = (issue.get("explanation") or "").strip()
        if expl:
            eline = "Giai thich: " + expl[:400]
            for part in [eline[i : i + 110] for i in range(0, len(eline), 110)]:
                if y < 48:
                    pdf.showPage()
                    pdf.setFont("Helvetica", 8)
                    y = height - 40
                pdf.drawString(40, y, part)
                y -= 10
        urls = issue.get("urls") or []
        if urls:
            uline = "URL(s): " + "; ".join(str(u) for u in urls[:12])
            for part in [uline[i : i + 110] for i in range(0, len(uline), 110)]:
                if y < 48:
                    pdf.showPage()
                    pdf.setFont("Helvetica", 8)
                    y = height - 40
                pdf.drawString(40, y, part)
                y -= 10
        y -= 4
    pdf.save()
    buffer.seek(0)
    safe_name = domain.replace("/", "-")[:60] or "audit"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="technical-audit-{safe_name}.pdf"'},
    )


@router.get("/api/audit/{audit_id}/export.gsheet")
def api_audit_export_gsheet(
    audit_id: str,
    current_user: User = Depends(get_current_user),
) -> Response:
    run = get_audit_for_user(audit_id, current_user.id)
    if not run:
        return JSONResponse(status_code=404, content={"detail": "Không tìm thấy bản quét."})
    out = io.StringIO()
    out.write("\ufeff")
    writer = csv.writer(out, delimiter="\t")
    writer.writerow(["url", "issue_type", "severity", "group", "message", "urls"])
    for issue in _group_audit_issues(run):
        writer.writerow(
            [
                issue.get("url") or "",
                issue.get("type") or "",
                issue.get("severity") or "",
                issue.get("checklist_group") or "",
                issue.get("message") or "",
                "; ".join(issue.get("urls") or []),
            ]
        )
    domain = (run.get("domain") or "audit").replace("/", "-")[:80]
    return Response(
        content=out.getvalue(),
        media_type="text/tab-separated-values; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="technical-audit-{domain}-gsheet.tsv"'},
    )


# IMPORTANT: keep this route AFTER `/api/audit/mine` and `/api/audit/{audit_id}/export.*`
# so that static paths like `/api/audit/mine` don't get captured by `{audit_id}`.
@router.get("/api/audit/{audit_id}/issues")
def api_audit_issues(
    audit_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    run = get_audit_for_user(audit_id, current_user.id)
    if not run:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản quét.")
    from app.services.api_payload_optimizer import collect_audit_issue_pool

    pool = collect_audit_issue_pool(run)
    items, total = paginate_list(pool, page, page_size)
    return JSONResponse(
        content={
            "audit_id": audit_id,
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": page * page_size < total,
        }
    )


@router.get("/api/audit/{audit_id}/issue-detail")
def api_audit_issue_detail(
    audit_id: str,
    issue_id: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    run = get_audit_for_user(audit_id, current_user.id)
    if not run:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản quét.")
    issue = find_audit_issue(run, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Không tìm thấy issue.")
    return JSONResponse(content={"audit_id": audit_id, "issue": issue})


@router.get("/api/audit/{audit_id}")
def api_audit_get_one(
    audit_id: str,
    lite: bool = Query(default=False, description="Bỏ mảng GSC/crawl nặng; giữ dashboard v2 + summary"),
    issues_page: int | None = Query(default=None, ge=1),
    issues_page_size: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    run = get_audit_for_user(audit_id, current_user.id)
    if not run:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản quét.")
    if lite or issues_page is not None:
        run = shape_audit_response(
            run,
            lite=lite,
            issues_page=issues_page,
            issues_page_size=issues_page_size,
        )
    return JSONResponse(content=run)


@router.get("/api/report")
def get_report(
    group: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> JSONResponse:
    ck_path = technical_checklist_path()
    if not ck_path:
        return JSONResponse(
            status_code=404,
            content={"detail": "Technical-SEO.txt was not found."},
        )
    report = build_seo_report_from_file(
        str(ck_path),
        group_filter=group,
        status_filter=status,
    )
    return JSONResponse(content=report)


@router.get("/api/action-plan")
def get_action_plan(
    group: str | None = Query(default=None),
    status: str | None = Query(default="needs_fix"),
    note: str | None = Query(default=None),
    notes_by_priority: str | None = Query(default=None),
    deploy_links_by_priority: str | None = Query(default=None),
    persist_notes: bool = Query(default=False),
    persist_deploy_links: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    notes_file = str(user_action_plan_notes_file(current_user.id))
    deploy_file = str(user_action_plan_deploy_file(current_user.id))
    ck_path = technical_checklist_path()
    if not ck_path:
        return JSONResponse(
            status_code=404,
            content={"detail": "Technical-SEO.txt was not found."},
        )

    report = build_seo_report_from_file(
        str(ck_path),
        group_filter=group,
        status_filter=status,
        user_id=current_user.id,
    )

    notes_map = load_notes_map(notes_file)
    deploy_map = load_deploy_links_map(deploy_file)
    plan_items = build_lean_action_plan(
        report,
        notes_map=notes_map,
        deploy_map=deploy_map,
        global_note=note,
    )

    updates = parse_notes_by_priority(notes_by_priority or "")
    if updates:
        for item in plan_items:
            priority = int(item.get("priority", 0) or 0)
            if priority in updates:
                item["NOTE"] = updates[priority]
                tk = str(item.get("task_key", ""))
                if tk:
                    notes_map[tk] = updates[priority]
        if persist_notes:
            save_notes_map(notes_file, notes_map)

    d_updates = parse_deploy_links_by_priority(deploy_links_by_priority or "")
    if d_updates:
        for item in plan_items:
            priority = int(item.get("priority", 0) or 0)
            if priority in d_updates:
                item["LINK TRIỂN KHAI"] = d_updates[priority]
                tk = str(item.get("task_key", ""))
                if tk:
                    deploy_map[tk] = d_updates[priority]
        if persist_deploy_links:
            save_deploy_links_map(deploy_file, deploy_map)

    for item in plan_items:
        item.pop("task_key", None)

    return JSONResponse(
        content={
            "total": len(plan_items),
            "items": plan_items,
        }
    )


@router.delete("/api/action-plan/notes")
def delete_action_plan_notes(
    priority: int | None = Query(default=None, ge=1),
    priorities: str | None = Query(default=None),
    reset_all: bool = Query(default=False),
    group: str | None = Query(default=None),
    status: str | None = Query(default="needs_fix"),
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    notes_file = str(user_action_plan_notes_file(current_user.id))
    deploy_file = str(user_action_plan_deploy_file(current_user.id))
    ck_path = technical_checklist_path()
    if not ck_path:
        return JSONResponse(
            status_code=404,
            content={"detail": "Technical-SEO.txt was not found."},
        )

    notes_map = load_notes_map(notes_file)
    deploy_map = load_deploy_links_map(deploy_file)
    if reset_all:
        save_notes_map(notes_file, {})
        save_deploy_links_map(deploy_file, {})
        return JSONResponse(content={"deleted": "all", "remaining": 0, "deploy_remaining": 0})

    target_priorities: set[int] = set()
    if priority is not None:
        target_priorities.add(priority)
    if priorities:
        for chunk in priorities.split(","):
            part = chunk.strip()
            if not part:
                continue
            try:
                parsed = int(part)
            except ValueError:
                continue
            if parsed > 0:
                target_priorities.add(parsed)

    if not target_priorities:
        return JSONResponse(
            status_code=400,
            content={
                "detail": "Provide priority/priorities or set reset_all=true.",
            },
        )

    report = build_seo_report_from_file(
        str(ck_path),
        group_filter=group,
        status_filter=status,
        user_id=current_user.id,
    )
    plan_items = build_lean_action_plan(
        report,
        notes_map=notes_map,
        deploy_map=deploy_map,
    )

    deleted = 0
    deleted_links = 0
    for item in plan_items:
        item_priority = int(item.get("priority", 0) or 0)
        if item_priority not in target_priorities:
            continue
        task_key = str(item.get("task_key", ""))
        if task_key and task_key in notes_map:
            del notes_map[task_key]
            deleted += 1
        if task_key and task_key in deploy_map:
            del deploy_map[task_key]
            deleted_links += 1

    save_notes_map(notes_file, notes_map)
    save_deploy_links_map(deploy_file, deploy_map)
    return JSONResponse(
        content={
            "deleted": deleted,
            "deleted_deploy_links": deleted_links,
            "requested_priorities": sorted(target_priorities),
            "remaining": len(notes_map),
            "deploy_remaining": len(deploy_map),
        }
    )


@router.get("/api/report.csv")
def export_report_csv(
    group: str | None = Query(default=None),
    status: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
) -> Response:
    notes_file = str(user_action_plan_notes_file(current_user.id))
    deploy_file = str(user_action_plan_deploy_file(current_user.id))
    ck_path = technical_checklist_path()
    if not ck_path:
        return JSONResponse(status_code=404, content={"detail": "Technical-SEO.txt was not found."})

    report = build_seo_report_from_file(
        str(ck_path),
        group_filter=group,
        status_filter=status,
        user_id=current_user.id,
    )
    rows = build_action_plan_rows(
        report,
        notes_map=load_notes_map(notes_file),
        deploy_map=load_deploy_links_map(deploy_file),
    )

    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.DictWriter(output, fieldnames=ACTION_PLAN_CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)

    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=seo-action-plan.csv"},
    )


@router.get("/api/report.pdf")
def export_report_pdf(
    group: str | None = Query(default=None),
    status: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    notes_file = str(user_action_plan_notes_file(current_user.id))
    deploy_file = str(user_action_plan_deploy_file(current_user.id))
    ck_path = technical_checklist_path()
    if not ck_path:
        return JSONResponse(status_code=404, content={"detail": "Technical-SEO.txt was not found."})

    report = build_seo_report_from_file(
        str(ck_path),
        group_filter=group,
        status_filter=status,
        user_id=current_user.id,
    )
    rows = build_action_plan_rows(
        report,
        notes_map=load_notes_map(notes_file),
        deploy_map=load_deploy_links_map(deploy_file),
    )

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="Missing dependency: reportlab") from exc

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 40

    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(40, y, "SEO Action Plan")
    y -= 24

    pdf.setFont("Helvetica", 10)
    for row in rows:
        checklist_short = (row.get("CHECKLIST") or "")[:100]
        line = (
            f"[{row.get('Ưu tiên')}] {row.get('Nhóm','')} | {row.get('HIỆN TRẠNG','')} | {checklist_short}"
        )
        for chunk in [line[i : i + 110] for i in range(0, len(line), 110)]:
            if y < 40:
                pdf.showPage()
                pdf.setFont("Helvetica", 10)
                y = height - 40
            pdf.drawString(40, y, chunk)
            y -= 14
        danhgia = f"Danh gia: {row.get('ĐÁNH GIÁ', '')}"
        chung = f"Dan chung: {(row.get('DẪN CHỨNG CHI TIẾT') or '')[:220]}"
        details = f"Giai phap: {row.get('GIẢI PHÁP', '')}"
        refs = f"Tham khao: {row.get('LINK THAM KHẢO', '')}"
        hientrang = f"Hien trang: {row.get('HIỆN TRẠNG', '')}"
        trienkhai = f"Link trien khai: {row.get('LINK TRIỂN KHAI', '')}"
        note_line = f"Note: {row.get('NOTE', '')}"
        for extra in (danhgia, chung, details, refs, hientrang, trienkhai, note_line):
            for chunk in [extra[i : i + 110] for i in range(0, len(extra), 110)]:
                if y < 40:
                    pdf.showPage()
                    pdf.setFont("Helvetica", 10)
                    y = height - 40
                pdf.drawString(40, y, chunk)
                y -= 14

    pdf.save()
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=seo-action-plan.pdf"},
    )


def _resolve_report_audit(
    current_user: User | None,
    audit_id: str | None,
) -> dict | None:
    if not current_user:
        return None
    aid = str(audit_id or "").strip()
    if aid:
        row = get_audit_for_user(aid, current_user.id)
        if row:
            return row
    return get_latest_audit(user_id=current_user.id)


@router.get("/report")
def report_page(
    request: Request,
    group: str | None = Query(default=None),
    status: str | None = Query(default=None),
    audit_id: str | None = Query(default=None),
):
    """
    SEO Dashboard shell. Security: never SSR per-user audit/quota/email — stale cookies
    must not leak another user's data. Client loads private data via authenticated APIs only.
    """
    tmpl_common = {
        "GROUP_SOLUTIONS_VI": GROUP_SOLUTIONS_VI,
        "GROUP_REFERENCES": GROUP_REFERENCES,
        "SEVERITY_LABEL_VI": SEVERITY_LABEL_VI,
        "STATUS_LABEL_VI": STATUS_LABEL_VI,
        "CHECKLIST_TITLE_VI": CHECKLIST_TITLE_VI,
    }
    dashboard = _build_dashboard_context(
        current_user=None,
        latest_audit=None,
        grouped_issues=[],
    )
    ctx = {
        "report": {"summary": {}, "groups": []},
        "report_full": {"summary": {}, "groups": []},
        "error": "",
        "selected_group": group or "",
        "selected_status": status or "",
        "selected_audit_id": str(audit_id or "").strip(),
        "latest_audit": None,
        "action_plan_rows": [],
        "latest_audit_grouped_issues": [],
        "dashboard": dashboard,
        "report_from_audit": False,
        "audit_summary": {},
    }
    ctx.update(tmpl_common)
    response = templates.TemplateResponse(
        request=request,
        name="report.html",
        context=ctx,
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Vary"] = "Cookie, Authorization"
    return response
