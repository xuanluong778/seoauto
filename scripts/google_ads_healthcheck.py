#!/usr/bin/env python3
"""Standalone Google Ads API health-check. Does not wire Keyword Research / DataForSEO.

Usage:
  PYTHONPATH=. .venv/bin/python scripts/google_ads_healthcheck.py
  PYTHONPATH=. .venv/bin/python scripts/google_ads_healthcheck.py --hierarchy
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / "env.local")
load_dotenv("/var/www/seoauto_vn_usr/data/www/shared/env.local")

# Google Ads geo / language constants
# https://developers.google.com/google-ads/api/data/geotargets  (Vietnam = 2704)
# https://developers.google.com/google-ads/api/data/codes-formats#languages  (Vietnamese = 1040)
VN_GEO_TARGET_ID = "2704"
VI_LANGUAGE_ID = "1040"
DEFAULT_SEED = "seo việt nam"


def _digits(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _env(name: str) -> str:
    return str(os.getenv(name) or "").strip()


def _missing_keys() -> list[str]:
    required = (
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
        "GOOGLE_ADS_CUSTOMER_ID",
    )
    return [k for k in required if not _env(k)]


def _client_config() -> dict[str, str | bool]:
    return {
        "developer_token": _env("GOOGLE_ADS_DEVELOPER_TOKEN"),
        "client_id": _env("GOOGLE_ADS_CLIENT_ID"),
        "client_secret": _env("GOOGLE_ADS_CLIENT_SECRET"),
        "refresh_token": _env("GOOGLE_ADS_REFRESH_TOKEN"),
        "login_customer_id": _digits(_env("GOOGLE_ADS_LOGIN_CUSTOMER_ID")),
        "use_proto_plus": True,
    }


def _format_google_ads_error(exc: BaseException) -> str:
    name = type(exc).__name__
    text = str(exc)
    if name == "RefreshError" or "unauthorized_client" in text:
        return (
            f"{name}: OAuth refresh bị Google từ chối (unauthorized_client). "
            "GOOGLE_ADS_REFRESH_TOKEN không khớp GOOGLE_ADS_CLIENT_ID/SECRET "
            "(token phát hành bởi client khác, hoặc client OAuth bị disable). "
            "Cần tạo refresh token mới bằng đúng cặp Client ID/Secret của Google Ads."
        )
    try:
        from google.ads.googleads.errors import GoogleAdsException
    except Exception:
        return f"{name}: {exc}"

    if not isinstance(exc, GoogleAdsException):
        return f"{type(exc).__name__}: {exc}"

    parts: list[str] = []
    request_id = getattr(exc, "request_id", None)
    if request_id:
        parts.append(f"request_id={request_id}")
    failure = getattr(exc, "failure", None)
    errors = list(getattr(failure, "errors", None) or [])
    if not errors:
        parts.append(str(exc))
        return " | ".join(parts)
    for err in errors:
        code = getattr(err, "error_code", None)
        code_name = ""
        if code is not None:
            for field in code._pb.DESCRIPTOR.fields:  # type: ignore[attr-defined]
                val = getattr(code, field.name, None)
                if val:
                    code_name = f"{field.name}={val}"
                    break
        msg = str(getattr(err, "message", "") or "").strip()
        trigger = getattr(err, "trigger", None)
        trigger_txt = ""
        if trigger is not None and getattr(trigger, "string_value", None):
            trigger_txt = str(trigger.string_value)
        chunk = " ".join(x for x in (code_name, msg, trigger_txt) if x)
        if chunk:
            parts.append(chunk)
    return " | ".join(parts) if parts else f"GoogleAdsException: {exc}"


def list_customer_clients(client, *, login_customer_id: str) -> list[dict[str, object]]:
    """MCC hierarchy via CustomerClient (query against login/MCC customer)."""
    query_visible = """
        SELECT
          customer_client.id,
          customer_client.descriptive_name,
          customer_client.manager,
          customer_client.level,
          customer_client.status,
          customer_client.hidden
        FROM customer_client
        WHERE customer_client.hidden = FALSE
    """
    query_hidden = """
        SELECT
          customer_client.id,
          customer_client.descriptive_name,
          customer_client.manager,
          customer_client.level,
          customer_client.status,
          customer_client.hidden
        FROM customer_client
        WHERE customer_client.hidden = TRUE
    """
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    ga_service = client.get_service("GoogleAdsService")
    for query in (query_visible, query_hidden):
        stream = ga_service.search_stream(customer_id=login_customer_id, query=query)
        for batch in stream:
            for row in batch.results:
                cc = row.customer_client
                cid = str(cc.id)
                if cid in seen:
                    continue
                seen.add(cid)
                status = cc.status.name if cc.status else ""
                rows.append(
                    {
                        "id": cid,
                        "name": str(cc.descriptive_name or ""),
                        "manager": bool(cc.manager),
                        "level": int(cc.level),
                        "status": status,
                        "hidden": bool(cc.hidden),
                    }
                )
    rows.sort(key=lambda r: (int(r["level"]), str(r["id"])))
    return rows


def list_accessible_customers(client) -> list[str]:
    customer_service = client.get_service("CustomerService")
    response = customer_service.list_accessible_customers()
    names = list(response.resource_names or [])
    out: list[str] = []
    for name in names:
        cid = str(name).rsplit("/", 1)[-1]
        out.append(_digits(cid) or str(name))
    return out


def generate_keyword_ideas(client, *, customer_id: str, seed: str) -> list[dict[str, object]]:
    idea_service = client.get_service("KeywordPlanIdeaService")
    google_ads_service = client.get_service("GoogleAdsService")
    geo_service = client.get_service("GeoTargetConstantService")

    request = client.get_type("GenerateKeywordIdeasRequest")
    request.customer_id = customer_id
    request.language = google_ads_service.language_constant_path(VI_LANGUAGE_ID)
    request.geo_target_constants.append(geo_service.geo_target_constant_path(VN_GEO_TARGET_ID))
    request.include_adult_keywords = False
    request.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
    request.keyword_seed.keywords.append(seed)

    rows: list[dict[str, object]] = []
    for idea in idea_service.generate_keyword_ideas(request=request):
        metrics = idea.keyword_idea_metrics
        competition = metrics.competition.name if metrics.competition else ""
        rows.append(
            {
                "keyword": idea.text,
                "search_volume": int(metrics.avg_monthly_searches or 0),
                "competition": competition,
                "cpc_low_micros": int(metrics.low_top_of_page_bid_micros or 0),
                "cpc_high_micros": int(metrics.high_top_of_page_bid_micros or 0),
            }
        )
        if len(rows) >= 8:
            break
    return rows


def _micros_to_vnd(micros: int) -> str:
    if micros <= 0:
        return "—"
    return f"{micros / 1_000_000:.2f}"


def main() -> int:
    hierarchy_only = "--hierarchy" in sys.argv
    print("Google Ads API health-check")
    if hierarchy_only:
        print("mode=CustomerClient hierarchy  (not wired to production)")
    else:
        print("geo=Vietnam(2704) language=Vietnamese(1040)  (not wired to production)")

    required = [
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
    ]
    if not hierarchy_only:
        required.append("GOOGLE_ADS_CUSTOMER_ID")
    missing = [k for k in required if not _env(k)]
    if missing:
        print("FAIL config: missing", ", ".join(missing))
        return 2

    customer_id = _digits(_env("GOOGLE_ADS_CUSTOMER_ID"))
    login_id = _digits(_env("GOOGLE_ADS_LOGIN_CUSTOMER_ID"))
    if len(login_id) < 8:
        print("FAIL config: GOOGLE_ADS_LOGIN_CUSTOMER_ID must be digits")
        return 2
    if not hierarchy_only and len(customer_id) < 8:
        print("FAIL config: GOOGLE_ADS_CUSTOMER_ID must be digits")
        return 2

    try:
        from google.ads.googleads.client import GoogleAdsClient
    except Exception as exc:
        print("FAIL import google-ads:", type(exc).__name__, exc)
        return 2

    try:
        client = GoogleAdsClient.load_from_dict(_client_config())
    except Exception as exc:
        print("FAIL client:", _format_google_ads_error(exc))
        return 1

    if hierarchy_only:
        try:
            tree = list_customer_clients(client, login_customer_id=login_id)
        except Exception as exc:
            print("FAIL CustomerClient:", _format_google_ads_error(exc))
            return 1
        print("PASS CustomerClient")
        print(f"MCC login_customer_id={login_id} rows={len(tree)}")
        print(f"{'customer_id':<14} {'manager':<8} {'level':<6} {'status':<12} {'hidden':<7} name")
        for row in tree:
            print(
                f"{str(row['id']):<14} "
                f"{str(row['manager']).lower():<8} "
                f"{row['level']:<6} "
                f"{str(row['status']):<12} "
                f"{str(row.get('hidden', False)).lower():<7} "
                f"{row['name']}"
            )
        suitable = [
            r
            for r in tree
            if r["manager"] is False and str(r["status"]) == "ENABLED"
        ]
        print("suitable GOOGLE_ADS_CUSTOMER_ID (manager=false + ENABLED):")
        if suitable:
            for row in suitable:
                print(f"  {row['id']}  {row['name']}")
        else:
            print("  (none)")
        probe_id = _digits(_env("GOOGLE_ADS_CUSTOMER_ID"))
        probe = probe_id if probe_id and probe_id != login_id else ""
        if probe:
            hit = next((r for r in tree if str(r["id"]) == probe), None)
            print(f"GOOGLE_ADS_CUSTOMER_ID={probe}:")
            if hit:
                print(
                    f"  under_mcc=yes  manager={str(hit['manager']).lower()}  "
                    f"level={hit['level']}  status={hit['status']}  name={hit['name']}"
                )
            else:
                print("  under_mcc=no  (không có trong CustomerClient của MCC này)")
        try:
            accounts = list_accessible_customers(client)
            print("ListAccessibleCustomers:", ", ".join(accounts) if accounts else "(none)")
        except Exception as exc:
            print("ListAccessibleCustomers:", _format_google_ads_error(exc))
            accounts = []
        if probe and probe not in {str(r["id"]) for r in tree}:
            ga_service = client.get_service("GoogleAdsService")
            try:
                q = (
                    "SELECT customer.id, customer.descriptive_name, "
                    "customer.manager, customer.status FROM customer"
                )
                found = False
                for batch in ga_service.search_stream(customer_id=probe, query=q):
                    for row in batch.results:
                        found = True
                        st = row.customer.status.name if row.customer.status else ""
                        print(
                            f"  direct customer query: id={row.customer.id} "
                            f"manager={str(row.customer.manager).lower()} "
                            f"status={st} name={row.customer.descriptive_name}"
                        )
                if not found:
                    print("  direct customer query: empty")
            except Exception as exc:
                print("  direct customer query FAIL:", _format_google_ads_error(exc))
        return 0

    try:
        accounts = list_accessible_customers(client)
    except Exception as exc:
        print("FAIL ListAccessibleCustomers:", _format_google_ads_error(exc))
        return 1

    print("PASS ListAccessibleCustomers")
    print("account_access_count:", len(accounts))
    print("account_ids:", ", ".join(accounts) if accounts else "(none)")
    if customer_id in accounts:
        print("GOOGLE_ADS_CUSTOMER_ID in accessible list: yes")
    else:
        print("GOOGLE_ADS_CUSTOMER_ID in accessible list: no (still trying GenerateKeywordIdeas)")

    seed = os.getenv("GOOGLE_ADS_HEALTHCHECK_SEED") or DEFAULT_SEED
    try:
        ideas = generate_keyword_ideas(client, customer_id=customer_id, seed=seed)
    except Exception as exc:
        print("FAIL GenerateKeywordIdeas:", _format_google_ads_error(exc))
        return 1

    print("PASS GenerateKeywordIdeas")
    print(f"seed={seed!r} customer_id={customer_id} results={len(ideas)}")
    print(f"{'keyword':<40} {'volume':>10} {'competition':<16} {'cpc_low':>10} {'cpc_high':>10}")
    for row in ideas:
        print(
            f"{str(row['keyword'])[:40]:<40} "
            f"{row['search_volume']:>10} "
            f"{str(row['competition']):<16} "
            f"{_micros_to_vnd(int(row['cpc_low_micros'])):>10} "
            f"{_micros_to_vnd(int(row['cpc_high_micros'])):>10}"
        )
    if not ideas:
        print("(API returned 0 keyword ideas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
