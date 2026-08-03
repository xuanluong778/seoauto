"""
Google Search Console API client — Search Analytics + URL Inspection.

Uses OAuth refresh tokens stored per user (google_token_store).
Official API only — no scraping of the GSC web UI.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.services.google_apis import gsc_list_sites, gsc_search_analytics_query, user_google_credentials

_LOG = logging.getLogger(__name__)

# GSC URL Inspection API daily quota per property (Google default ~2000/day; we stay conservative)
DEFAULT_INSPECTION_DAILY_HINT = 2000


class GscClientError(Exception):
    """Base GSC client error with user-facing message."""

    def __init__(self, message: str, *, code: str = "gsc_error", partial: bool = False):
        super().__init__(message)
        self.code = code
        self.partial = partial


class GscNotConnectedError(GscClientError):
    def __init__(self):
        super().__init__(
            "Chưa kết nối Google Search Console. Bấm «Kết nối Google» trên trang Technical Analysis.",
            code="not_connected",
        )


class GscPermissionError(GscClientError):
    def __init__(self, detail: str = ""):
        msg = "Tài khoản Google không có quyền đọc property GSC này."
        if detail:
            msg += f" ({detail})"
        super().__init__(msg, code="permission_denied")


class GscQuotaError(GscClientError):
    def __init__(self, detail: str = ""):
        msg = "Đã hết quota URL Inspection API của Google hôm nay."
        if detail:
            msg += f" ({detail})"
        super().__init__(msg, code="quota_exceeded", partial=True)


def resolve_gsc_date_range(
    gsc_date_range: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[str, str]:
    """Return (start_date, end_date) as YYYY-MM-DD for Search Analytics."""
    today = date.today()
    dr = (gsc_date_range or "28d").strip().lower()
    if dr == "custom" and start_date and end_date:
        return start_date.strip()[:10], end_date.strip()[:10]
    if dr == "90d":
        return (today - timedelta(days=89)).isoformat(), today.isoformat()
    # default 28d
    return (today - timedelta(days=27)).isoformat(), today.isoformat()


def _http_error_message(exc: HttpError) -> str:
    try:
        content = exc.content.decode("utf-8") if exc.content else ""
        if content:
            return content[:400]
    except Exception:
        pass
    return str(exc)


def _is_quota_error(exc: HttpError) -> bool:
    if exc.resp.status == 429:
        return True
    msg = _http_error_message(exc).lower()
    return "quota" in msg or "rate limit" in msg or "resource_exhausted" in msg


def _is_permission_error(exc: HttpError) -> bool:
    if exc.resp.status in (401, 403):
        return True
    msg = _http_error_message(exc).lower()
    return "permission" in msg or "forbidden" in msg or "not verified" in msg


class GscClient:
    """Thin wrapper around Search Console v1 for one user session."""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self._creds = user_google_credentials(user_id)
        if not self._creds:
            raise GscNotConnectedError()
        self._svc = build("searchconsole", "v1", credentials=self._creds, cache_discovery=False)

    @classmethod
    def for_user(cls, user_id: int) -> GscClient | None:
        try:
            return cls(user_id)
        except GscNotConnectedError:
            return None

    def list_sites(self) -> dict[str, Any]:
        try:
            return gsc_list_sites(self._creds)
        except HttpError as exc:
            if _is_permission_error(exc):
                raise GscPermissionError(_http_error_message(exc)) from exc
            raise GscClientError(f"Search Console API: {_http_error_message(exc)}", code="api_error") from exc

    def query_search_analytics(
        self,
        *,
        site_url: str,
        start_date: str,
        end_date: str,
        dimensions: list[str] | None = None,
        filters: list[dict[str, Any]] | None = None,
        row_limit: int = 250,
        start_row: int = 0,
        aggregation_type: str | None = None,
    ) -> dict[str, Any]:
        """
        Search Analytics API — clicks, impressions, ctr, position by dimensions.

        dimensions: page, query, device, country, date, …
        filters: [{"dimension": "page", "operator": "equals", "expression": "https://..."}]
        """
        body: dict[str, Any] = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": dimensions or ["page"],
            "rowLimit": min(max(int(row_limit), 1), 25000),
            "startRow": max(0, int(start_row)),
        }
        if filters:
            body["dimensionFilterGroups"] = [{"filters": filters}]
        if aggregation_type:
            body["aggregationType"] = aggregation_type
        try:
            return self._svc.searchanalytics().query(siteUrl=site_url, body=body).execute()
        except HttpError as exc:
            if _is_permission_error(exc):
                raise GscPermissionError(_http_error_message(exc)) from exc
            if _is_quota_error(exc):
                raise GscQuotaError(_http_error_message(exc)) from exc
            raise GscClientError(f"Search Analytics API: {_http_error_message(exc)}", code="api_error") from exc

    def inspect_url(self, *, site_url: str, inspection_url: str) -> dict[str, Any]:
        """
        URL Inspection API — index verdict, coverage, canonicals, last crawl.

        Returns normalized dict with index_verdict, coverage_state, user_canonical,
        google_canonical, last_crawl_time, raw inspection payload.
        """
        body = {
            "inspectionUrl": inspection_url,
            "siteUrl": site_url,
        }
        try:
            raw = self._svc.urlInspection().index().inspect(body=body).execute()
        except HttpError as exc:
            if _is_quota_error(exc):
                raise GscQuotaError(_http_error_message(exc)) from exc
            if _is_permission_error(exc):
                raise GscPermissionError(_http_error_message(exc)) from exc
            raise GscClientError(
                f"URL Inspection API: {_http_error_message(exc)}",
                code="inspection_error",
                partial=True,
            ) from exc
        return normalize_inspection_result(raw, inspection_url=inspection_url)

    def fetch_page_performance(
        self,
        *,
        site_url: str,
        start_date: str,
        end_date: str,
        row_limit: int = 5000,
    ) -> list[dict[str, Any]]:
        """Aggregate performance metrics keyed by page URL."""
        rows_out: list[dict[str, Any]] = []
        start_row = 0
        page_size = min(2500, row_limit)
        while start_row < row_limit:
            batch_limit = min(page_size, row_limit - start_row)
            data = self.query_search_analytics(
                site_url=site_url,
                start_date=start_date,
                end_date=end_date,
                dimensions=["page"],
                row_limit=batch_limit,
                start_row=start_row,
            )
            rows = data.get("rows") or []
            if not rows:
                break
            for row in rows:
                keys = row.get("keys") or []
                page_url = keys[0] if keys else ""
                rows_out.append(
                    {
                        "page": page_url,
                        "clicks": int(row.get("clicks") or 0),
                        "impressions": int(row.get("impressions") or 0),
                        "ctr": float(row.get("ctr") or 0.0),
                        "position": float(row.get("position") or 0.0),
                    }
                )
            if len(rows) < batch_limit:
                break
            start_row += len(rows)
        return rows_out

    def fetch_page_query_performance(
        self,
        *,
        site_url: str,
        start_date: str,
        end_date: str,
        page_url: str,
        row_limit: int = 25,
    ) -> list[dict[str, Any]]:
        """Top queries for a single page (optional enrichment)."""
        data = self.query_search_analytics(
            site_url=site_url,
            start_date=start_date,
            end_date=end_date,
            dimensions=["query", "page"],
            filters=[{"dimension": "page", "operator": "equals", "expression": page_url}],
            row_limit=row_limit,
        )
        out: list[dict[str, Any]] = []
        for row in data.get("rows") or []:
            keys = row.get("keys") or []
            query = keys[0] if keys else ""
            out.append(
                {
                    "query": query,
                    "page": page_url,
                    "clicks": int(row.get("clicks") or 0),
                    "impressions": int(row.get("impressions") or 0),
                    "ctr": float(row.get("ctr") or 0.0),
                    "position": float(row.get("position") or 0.0),
                }
            )
        return out


def normalize_inspection_result(raw: dict[str, Any], *, inspection_url: str) -> dict[str, Any]:
    """Flatten URL Inspection API response for audit payload."""
    ir = raw.get("inspectionResult") or {}
    idx = ir.get("indexStatusResult") or {}
    return {
        "inspection_url": inspection_url,
        "inspection_result_link": ir.get("inspectionResultLink"),
        "index_verdict": idx.get("verdict"),
        "coverage_state": idx.get("coverageState"),
        "robots_txt_state": idx.get("robotsTxtState"),
        "indexing_state": idx.get("indexingState"),
        "page_fetch_state": idx.get("pageFetchState"),
        "user_canonical": idx.get("userCanonical"),
        "google_canonical": idx.get("googleCanonical"),
        "last_crawl_time": idx.get("lastCrawlTime"),
        "referring_urls": idx.get("referringUrls") or [],
        "sitemap_urls": idx.get("sitemap") or [],
        "raw": raw,
    }
