"""Scan-to-scan SEO comparison helpers."""

from typing import NamedTuple

from sqlalchemy.orm import Session

from app.models.seo import Page, Scan, ScanIssue


class CompareResult(NamedTuple):
    current_scan_id: int
    previous_scan_id: int
    score_diff: int
    issues_fixed: int
    issues_added: int
    pages_improved: int
    pages_declined: int
    message: str | None


def _load_pages_by_scan(db: Session, scan_id: int) -> list[tuple[str, int]]:
    """Return list of (url, page_score) for scan."""
    rows = (
        db.query(Page.url, Page.page_score)
        .filter(Page.scan_id == scan_id)
        .all()
    )
    return [(url, score) for url, score in rows]


def _load_issue_keys_by_scan(db: Session, scan_id: int) -> set[tuple[str, str]]:
    """Issue identity = (type, page_url)."""
    rows = (
        db.query(ScanIssue.type, Page.url)
        .join(Page, ScanIssue.page_id == Page.id)
        .filter(Page.scan_id == scan_id)
        .all()
    )
    return {(t, url) for t, url in rows}


def compare_scans(db: Session, current_scan: Scan, previous_scan: Scan) -> CompareResult:
    cur_pages = _load_pages_by_scan(db, current_scan.id)
    prev_pages = _load_pages_by_scan(db, previous_scan.id)

    prev_by_url = {url: score for url, score in prev_pages}
    cur_by_url = {url: score for url, score in cur_pages}

    pages_improved = 0
    pages_declined = 0
    for url, cur_score in cur_by_url.items():
        if url not in prev_by_url:
            continue
        prev_score = prev_by_url[url]
        if cur_score > prev_score:
            pages_improved += 1
        elif cur_score < prev_score:
            pages_declined += 1

    prev_issues = _load_issue_keys_by_scan(db, previous_scan.id)
    cur_issues = _load_issue_keys_by_scan(db, current_scan.id)

    issues_fixed = len(prev_issues - cur_issues)
    issues_added = len(cur_issues - prev_issues)

    score_diff = current_scan.seo_score - previous_scan.seo_score

    return CompareResult(
        current_scan_id=current_scan.id,
        previous_scan_id=previous_scan.id,
        score_diff=score_diff,
        issues_fixed=issues_fixed,
        issues_added=issues_added,
        pages_improved=pages_improved,
        pages_declined=pages_declined,
        message=None,
    )
