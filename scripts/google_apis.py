"""Google Search Console + Google Analytics (GA4) — credentials & API calls."""

from __future__ import annotations

from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.core.settings import GOOGLE_OAUTH_SCOPES, get_google_oauth_settings
from app.services.google_token_store import get_google_refresh_token


def user_google_credentials(user_id: int) -> Credentials | None:
    rt = get_google_refresh_token(user_id)
    if not rt:
        return None
    s = get_google_oauth_settings()
    if not s:
        return None
    creds = Credentials(
        token=None,
        refresh_token=rt,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=s["client_id"],
        client_secret=s["client_secret"],
        scopes=list(GOOGLE_OAUTH_SCOPES),
    )
    creds.refresh(Request())
    return creds


def gsc_list_sites(creds: Credentials) -> dict[str, Any]:
    svc = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
    return svc.sites().list().execute()


def gsc_search_analytics_query(
    creds: Credentials,
    *,
    site_url: str,
    start_date: str,
    end_date: str,
    dimensions: list[str] | None = None,
    row_limit: int = 250,
) -> dict[str, Any]:
    """site_url: đúng như trong GSC, ví dụ https://www.example.com/ hoặc sc-domain:example.com"""
    svc = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
    body: dict[str, Any] = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": dimensions or ["query", "page"],
        "rowLimit": min(max(row_limit, 1), 25000),
    }
    return svc.searchanalytics().query(siteUrl=site_url, body=body).execute()


def ga4_list_account_summaries(creds: Credentials) -> dict[str, Any]:
    admin = build("analyticsadmin", "v1beta", credentials=creds, cache_discovery=False)
    return admin.accountSummaries().list().execute()


def ga4_run_report(
    creds: Credentials,
    *,
    property_resource: str,
    start_date: str,
    end_date: str,
    metrics: list[str],
    dimensions: list[str] | None = None,
) -> dict[str, Any]:
    """
    property_resource: 'properties/123456789' hoặc chỉ số '123456789'.
    start_date / end_date: YYYY-MM-DD hoặc '7daysAgo', 'today' (theo GA4 Data API).
    """
    pid = property_resource.strip()
    if pid and not pid.startswith("properties/"):
        pid = f"properties/{pid}"
    svc = build("analyticsdata", "v1beta", credentials=creds, cache_discovery=False)
    body: dict[str, Any] = {
        "dateRanges": [{"startDate": start_date, "endDate": end_date}],
        "metrics": [{"name": m} for m in metrics],
    }
    if dimensions:
        body["dimensions"] = [{"name": d} for d in dimensions]
    return svc.properties().runReport(property=pid, body=body).execute()
