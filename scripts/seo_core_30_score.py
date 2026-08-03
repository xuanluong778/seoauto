"""
SEO Core 30 yếu tố — wrapper cho Content Auto Update.

Tái sử dụng evaluate_publish_checklist (10 nhóm / 30 yếu tố / 100 điểm) từ Content AI.
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from app.services.content_ai_publish_checklist import evaluate_publish_checklist
from app.services.content_update_agent import validate_preserved_markup

_MIN_WORDS_AFTER = 50


def score_seo_core_30(
    *,
    title: str = "",
    meta_description: str = "",
    content_html: str = "",
    primary_keyword: str = "",
    slug: str = "",
    secondary_keywords: list[str] | None = None,
) -> dict[str, Any]:
    """Chấm SEO Core 30 yếu tố (0–100)."""
    return evaluate_publish_checklist(
        title=title,
        meta_description=meta_description,
        content_html=content_html,
        primary_keyword=primary_keyword,
        slug=slug,
        secondary_keywords=secondary_keywords,
    )


def factors_not_passed(result: dict[str, Any], *, severe_only: bool = False) -> list[dict[str, Any]]:
    """Yếu tố chưa đạt: failed (+ warning nếu không severe_only)."""
    out: list[dict[str, Any]] = []
    for f in result.get("factors") or []:
        st = str(f.get("status") or "")
        if severe_only:
            if st == "failed":
                out.append(f)
        elif st in ("failed", "warning"):
            out.append(f)
    return out


def factors_failed_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Chỉ yếu tố status=failed."""
    return [f for f in (result.get("factors") or []) if str(f.get("status") or "") == "failed"]


def factors_warning_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Chỉ yếu tố status=warning."""
    return [f for f in (result.get("factors") or []) if str(f.get("status") or "") == "warning"]


def seo_factor_counts(result: dict[str, Any]) -> dict[str, int]:
    """Đếm đạt / cảnh báo / chưa đạt trong 30 yếu tố."""
    passed = warning = failed = 0
    for f in result.get("factors") or []:
        st = str(f.get("status") or "")
        if st == "passed":
            passed += 1
        elif st == "warning":
            warning += 1
        elif st == "failed":
            failed += 1
    total = passed + warning + failed
    return {
        "passed": passed,
        "warning": warning,
        "failed": failed,
        "total": total or len(result.get("factors") or []),
    }


def build_seo_update_summary(
    *,
    comparison: dict[str, Any],
    preserve_warnings: list[str] | None = None,
    score_regressed: bool = False,
) -> str:
    """Tóm tắt kết quả AI theo SEO Core 30."""
    before = comparison.get("before_score", "—")
    after = comparison.get("after_score", "—")
    delta = comparison.get("delta", 0)
    improved = comparison.get("improved_factors") or []
    failed_after = comparison.get("failed_after") or []
    parts = [f"SEO Core {before} → {after} (Δ{delta:+d})."]
    if improved:
        labels = ", ".join(str(x.get("label") or x.get("id") or "") for x in improved[:5])
        extra = f" +{len(improved) - 5} khác" if len(improved) > 5 else ""
        parts.append(f"Đã cải thiện {len(improved)} yếu tố: {labels}{extra}.")
    if failed_after:
        parts.append(f"Còn {len(failed_after)} yếu tố chưa đạt/cảnh báo.")
    if score_regressed:
        parts.append("Cảnh báo: điểm giảm — không publish live.")
    if preserve_warnings:
        parts.append(f"Markup: {len(preserve_warnings)} cảnh báo.")
    return " ".join(parts)


def compare_seo_scores(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """So sánh điểm và yếu tố trước/sau."""
    before_score = int(before.get("score") or 0)
    after_score = int(after.get("score") or 0)
    before_map = {str(f.get("id")): f for f in (before.get("factors") or []) if f.get("id")}
    after_map = {str(f.get("id")): f for f in (after.get("factors") or []) if f.get("id")}

    improved: list[dict[str, Any]] = []
    regressed: list[dict[str, Any]] = []
    for fid, bf in before_map.items():
        af = after_map.get(fid)
        if not af:
            continue
        b_pts = float(bf.get("score") or 0)
        a_pts = float(af.get("score") or 0)
        b_st = str(bf.get("status") or "")
        a_st = str(af.get("status") or "")
        if a_pts > b_pts or (b_st in ("failed", "warning") and a_st == "passed"):
            improved.append({
                "id": fid,
                "label": af.get("label") or bf.get("label"),
                "before_score": b_pts,
                "after_score": a_pts,
                "before_status": b_st,
                "after_status": a_st,
            })
        elif a_pts < b_pts or (b_st == "passed" and a_st in ("failed", "warning")):
            regressed.append({
                "id": fid,
                "label": af.get("label") or bf.get("label"),
                "before_score": b_pts,
                "after_score": a_pts,
                "before_status": b_st,
                "after_status": a_st,
            })

    return {
        "before_score": before_score,
        "after_score": after_score,
        "delta": after_score - before_score,
        "failed_before": factors_not_passed(before),
        "failed_after": factors_not_passed(after),
        "severe_after": factors_not_passed(after, severe_only=True),
        "improved_factors": improved,
        "regressed_factors": regressed,
        "grade_before": before.get("grade_label"),
        "grade_after": after.get("grade_label"),
    }


def _heading_counts(html: str) -> dict[str, int]:
    try:
        soup = BeautifulSoup(str(html or "")[:800_000], "html.parser")
    except Exception:
        return {"h1": 0, "h2": 0, "h3": 0, "total": 0}
    h1 = len(soup.find_all("h1"))
    h2 = len(soup.find_all("h2"))
    h3 = len(soup.find_all("h3"))
    return {"h1": h1, "h2": h2, "h3": h3, "total": h1 + h2 + h3}


def _word_count(html: str) -> int:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return len(re.findall(r"[\wà-ỹ]+", text, re.I))


def validate_content_integrity(old_content: str, new_content: str) -> list[str]:
    """Blocker: mất markup, heading, ảnh, nội dung rỗng/ngắn bất thường."""
    blockers: list[str] = []
    warnings = validate_preserved_markup(old_content, new_content)
    for w in warnings:
        wl = w.lower()
        if "shortcode" in wl:
            blockers.append(w)
        elif "wp-block" in wl or "gutenberg" in wl:
            blockers.append(w)
        elif "img" in wl:
            blockers.append(f"Mất ảnh: {w}")

    old_h = _heading_counts(old_content)
    new_h = _heading_counts(new_content)
    if old_h["h2"] > 0 and new_h["h2"] < old_h["h2"]:
        blockers.append(f"Mất H2: {old_h['h2']} → {new_h['h2']}")
    if old_h["h3"] > 0 and new_h["h3"] < old_h["h3"]:
        blockers.append(f"Mất H3: {old_h['h3']} → {new_h['h3']}")

    old_wc = _word_count(old_content)
    new_wc = _word_count(new_content)
    if not (new_content or "").strip():
        blockers.append("Nội dung mới rỗng.")
    elif new_wc < _MIN_WORDS_AFTER:
        blockers.append(f"Nội dung mới quá ngắn ({new_wc} từ, tối thiểu {_MIN_WORDS_AFTER}).")
    elif old_wc >= 80 and new_wc < int(old_wc * 0.7):
        blockers.append(f"Nội dung mới ngắn bất thường: {old_wc} → {new_wc} từ.")

    return blockers


def group_checklist_items(checks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        "ok": [c for c in checks if c.get("status") == "ok"],
        "warn": [c for c in checks if c.get("status") == "warn"],
        "block": [c for c in checks if c.get("status") == "block"],
    }


def build_publish_checklist(
    *,
    backup_id: str | None,
    seo_comparison: dict[str, Any] | None,
    integrity_blockers: list[str],
    preserve_warnings: list[str] | None = None,
    new_content: str = "",
) -> dict[str, Any]:
    """Checklist trước publish — mỗi mục ok/block/warn."""
    comp = seo_comparison or {}
    before_score = comp.get("before_score")
    after_score = comp.get("after_score")
    severe = comp.get("severe_after") or []

    checks: list[dict[str, Any]] = []

    def _add(item_id: str, label: str, ok: bool, detail: str = "") -> None:
        checks.append({
            "id": item_id,
            "label": label,
            "status": "ok" if ok else "block",
            "detail": detail,
        })

    _add("backup", "Đã backup bản cũ", bool(backup_id), backup_id or "Chưa có backup — chạy Preview")
    if before_score is not None and after_score is not None:
        _add(
            "score",
            "Điểm SEO Core sau ≥ trước",
            int(after_score) >= int(before_score),
            f"{before_score} → {after_score} (Δ {comp.get('delta', 0):+d})",
        )
    else:
        _add("score", "Đã chấm SEO Core trước/sau", False, "Chưa có điểm so sánh — chạy Generate")

    _add("integrity", "Giữ shortcode / Gutenberg / ảnh / heading", not integrity_blockers, "; ".join(integrity_blockers[:3]))
    _add("severe", "Không còn lỗi SEO Core nghiêm trọng", not severe, f"{len(severe)} yếu tố failed")

    warn_markup = [w for w in (preserve_warnings or []) if w not in integrity_blockers]
    if warn_markup:
        checks.append({
            "id": "markup_warn",
            "label": "Cảnh báo markup",
            "status": "warn",
            "detail": "; ".join(warn_markup[:4]),
        })

    score_ok = before_score is not None and after_score is not None and int(after_score) >= int(before_score)
    score_regressed = before_score is not None and after_score is not None and int(after_score) < int(before_score)

    draft_blockers = [
        c["detail"] or c["label"]
        for c in checks
        if c["status"] == "block" and c["id"] not in ("score", "severe")
    ]
    draft_blockers.extend(integrity_blockers)

    live_blockers = list(draft_blockers)
    if score_regressed:
        live_blockers.append(f"Điểm SEO giảm: {before_score} → {after_score}")
    if severe:
        live_blockers.append(f"Còn {len(severe)} lỗi SEO Core blocker")

    has_content = bool((new_content or "").strip())
    draft_ok = bool(backup_id) and has_content
    draft_reasons: list[str] = []
    if not backup_id:
        draft_reasons.append("Chưa backup — chạy Preview.")
    if not has_content:
        draft_reasons.append("Nội dung mới rỗng.")

    grouped = group_checklist_items(checks)

    return {
        "checks": checks,
        "grouped": grouped,
        "blockers": live_blockers,
        "can_publish": len(live_blockers) == 0,
        "can_publish_live": len(live_blockers) == 0,
        "can_save_draft": draft_ok,
        "draft_block_reasons": draft_reasons,
        "live_block_reasons": live_blockers,
        "score_regressed": score_regressed,
        "draft_blockers": draft_blockers,
        "live_blockers": live_blockers,
    }


def evaluate_publish_gate(
    *,
    backup_id: str | None,
    seo_before: dict[str, Any] | None,
    seo_after: dict[str, Any] | None,
    old_content: str,
    new_content: str,
    preserve_warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Publish gate — raise không ở đây, trả can_publish + blockers."""
    comparison = compare_seo_scores(seo_before or {}, seo_after or {}) if seo_before and seo_after else {}
    integrity = validate_content_integrity(old_content, new_content)
    checklist = build_publish_checklist(
        backup_id=backup_id,
        seo_comparison=comparison,
        integrity_blockers=integrity,
        preserve_warnings=preserve_warnings,
        new_content=new_content,
    )
    return {
        "comparison": comparison,
        "integrity_blockers": integrity,
        "checklist": checklist,
        "can_publish": checklist["can_publish_live"],
        "can_publish_live": checklist["can_publish_live"],
        "can_save_draft": checklist["can_save_draft"],
        "score_regressed": checklist.get("score_regressed", False),
        "blockers": checklist["blockers"],
    }
