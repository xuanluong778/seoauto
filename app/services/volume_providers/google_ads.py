"""Native Google Ads Keyword Planner provider (ideas + historical metrics).

Does not log tokens/secrets. Reads customer IDs from env only.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Callable, TypeVar

_LOG = logging.getLogger("google_ads.keyword")
_CLIENT_LOCK = threading.Lock()
_FLIGHT_LOCK = threading.Lock()
_FLIGHTS: dict[str, dict[str, Any]] = {}
_CLIENT = None

VN_GEO_TARGET_ID = "2704"
VI_LANGUAGE_ID = "1040"

_SF_POLL_S = 0.05
_RELEASE_LOCK_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('del', KEYS[1]) else return 0 end"
)

_T = TypeVar("_T")

_MONTH_NAME_TO_NUM = {
    "JANUARY": 1,
    "FEBRUARY": 2,
    "MARCH": 3,
    "APRIL": 4,
    "MAY": 5,
    "JUNE": 6,
    "JULY": 7,
    "AUGUST": 8,
    "SEPTEMBER": 9,
    "OCTOBER": 10,
    "NOVEMBER": 11,
    "DECEMBER": 12,
}


def _digits(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _env(name: str) -> str:
    return str(os.getenv(name) or "").strip()


def google_ads_configured() -> bool:
    keys = (
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
        "GOOGLE_ADS_CUSTOMER_ID",
    )
    if any(not _env(k) for k in keys):
        return False
    flag = (_env("GOOGLE_ADS_KEYWORD_ENABLED") or "1").lower()
    return flag in ("1", "true", "yes")


def geo_language_ids(*, country: str | None, language: str | None) -> tuple[str, str]:
    geo = _digits(_env("GOOGLE_ADS_GEO_TARGET_ID")) or VN_GEO_TARGET_ID
    lang = _digits(_env("GOOGLE_ADS_LANGUAGE_ID")) or VI_LANGUAGE_ID
    c = (country or "").strip().lower()
    l = (language or "").strip().lower()
    if c in ("", "vn", "vietnam", "vi-vn"):
        geo = VN_GEO_TARGET_ID
    if l in ("", "vi", "vi-vn", "vietnamese"):
        lang = VI_LANGUAGE_ID
    return geo, lang


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if hasattr(value, "value") and not isinstance(value, (int, float, str, bytes)):
        value = getattr(value, "value", None)
        if value is None:
            return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _micros_to_currency(micros: int | None) -> float:
    n = _as_int(micros)
    if n is None or n <= 0:
        return 0.0
    return round(n / 1_000_000.0, 4)


def _timeout_s() -> float:
    return max(5.0, min(60.0, float(os.getenv("GOOGLE_ADS_TIMEOUT_SECONDS", "30") or 30)))


def _retry_max() -> int:
    return max(1, min(5, int(os.getenv("GOOGLE_ADS_RETRY_MAX", "3") or 3)))


def _client_config() -> dict[str, str | bool]:
    return {
        "developer_token": _env("GOOGLE_ADS_DEVELOPER_TOKEN"),
        "client_id": _env("GOOGLE_ADS_CLIENT_ID"),
        "client_secret": _env("GOOGLE_ADS_CLIENT_SECRET"),
        "refresh_token": _env("GOOGLE_ADS_REFRESH_TOKEN"),
        "login_customer_id": _digits(_env("GOOGLE_ADS_LOGIN_CUSTOMER_ID")),
        "use_proto_plus": True,
    }


def _reset_client() -> None:
    global _CLIENT
    with _CLIENT_LOCK:
        _CLIENT = None


def _get_client():
    global _CLIENT
    if not google_ads_configured():
        return None
    with _CLIENT_LOCK:
        if _CLIENT is None:
            from google.ads.googleads.client import GoogleAdsClient

            _CLIENT = GoogleAdsClient.load_from_dict(_client_config())
        return _CLIENT


def _error_code_name(exc: BaseException) -> str:
    try:
        from google.ads.googleads.errors import GoogleAdsException
    except Exception:
        return type(exc).__name__
    if not isinstance(exc, GoogleAdsException):
        return type(exc).__name__
    failure = getattr(exc, "failure", None)
    for err in list(getattr(failure, "errors", None) or []):
        code = getattr(err, "error_code", None)
        if code is None:
            continue
        for field in code._pb.DESCRIPTOR.fields:  # type: ignore[attr-defined]
            val = getattr(code, field.name, None)
            if val:
                return f"{field.name}={val}"
    return "GoogleAdsException"


def _request_id(exc: BaseException) -> str:
    return str(getattr(exc, "request_id", "") or "")


def _is_retryable(exc: BaseException) -> bool:
    name = type(exc).__name__
    text = str(exc).upper()
    code = _error_code_name(exc).upper()
    # Quota / rate-limit: fail fast — retries burn more quota and hold DB open.
    if "RESOURCE_EXHAUSTED" in code or "RESOURCE_EXHAUSTED" in text:
        return False
    if "RATE_LIMIT" in code or "TOO_MANY_REQUESTS" in name.upper() or "TOO_MANY_REQUESTS" in code:
        return False
    if name in ("RetryError", "DeadlineExceeded", "ServiceUnavailable", "GoogleAdsException"):
        if any(tok in text for tok in ("UNAVAILABLE", "DEADLINE", "TIMEOUT", "INTERNAL")):
            return True
    if "UNAVAILABLE" in code or "DEADLINE" in code:
        return True
    if "TIMEOUT" in name.upper() or "TIMEOUT" in text:
        return True
    return False


def _call_with_retry(fn: Callable[[], _T], *, label: str) -> _T:
    delay = 0.6
    last: BaseException | None = None
    attempts = _retry_max()
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:
            last = exc
            rid = _request_id(exc)
            code = _error_code_name(exc)
            _LOG.warning(
                "google_ads_%s_error attempt=%s code=%s request_id=%s",
                label,
                i + 1,
                code,
                rid or "-",
            )
            if i + 1 >= attempts or not _is_retryable(exc):
                raise
            time.sleep(delay)
            delay = min(delay * 2.0, 8.0)
    assert last is not None
    raise last


def _sf_lock_key(flight_key: str) -> str:
    return f"ads_sf:{flight_key}"


def _sf_result_key(flight_key: str) -> str:
    return f"ads_sf_res:{flight_key}"


def _sf_ttl_s(wait_s: float) -> int:
    try:
        n = int(wait_s or 90)
    except (TypeError, ValueError):
        n = 90
    return max(2, min(180, n))


def _redis_client():
    try:
        import redis

        url = (os.getenv("REDIS_URL") or "redis://127.0.0.1:6379/0").strip()
        return redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=1.0,
            socket_timeout=1.5,
        )
    except Exception:
        return None


def _release_lock(r: Any, lock_key: str, token: str) -> None:
    if r is None or not token:
        return
    try:
        r.eval(_RELEASE_LOCK_LUA, 1, lock_key, token)
    except Exception:
        _LOG.warning("google_ads_singleflight_release_fail")


def _pack_ok(value: Any) -> str:
    return json.dumps({"s": "ok", "v": value}, ensure_ascii=False)


def _pack_err() -> str:
    return json.dumps({"s": "err"})


def _unpack_result(raw: Any) -> tuple[str, Any] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    status = data.get("s")
    if status == "ok":
        return ("ok", data.get("v"))
    if status == "err":
        return ("err", None)
    return None


def _singleflight_memory(key: str, fn: Callable[[], _T], *, wait_s: float) -> _T | None:
    """Process-local lock used when Redis is unavailable."""
    with _FLIGHT_LOCK:
        flight = _FLIGHTS.get(key)
        mine = flight is None
        if mine:
            flight = {"ev": threading.Event(), "result": None, "error": None}
            _FLIGHTS[key] = flight
    if not mine:
        flight["ev"].wait(timeout=wait_s)
        err = flight.get("error")
        if err is not None:
            raise err
        return flight.get("result")
    try:
        flight["result"] = fn()
        return flight["result"]
    except Exception as exc:
        flight["error"] = exc
        raise
    finally:
        flight["ev"].set()
        with _FLIGHT_LOCK:
            _FLIGHTS.pop(key, None)


def _run_winner(
    key: str,
    fn: Callable[[], _T],
    r: Any,
    lock_key: str,
    token: str,
    ttl: int,
    wait_s: float,
) -> _T | None:
    res_key = _sf_result_key(key)
    with _FLIGHT_LOCK:
        flight = _FLIGHTS.get(key)
        if flight is None:
            flight = {"ev": threading.Event(), "result": None, "error": None}
            _FLIGHTS[key] = flight
            mine_mem = True
        else:
            mine_mem = False
    if not mine_mem:
        try:
            flight["ev"].wait(timeout=wait_s)
            err = flight.get("error")
            if err is not None:
                raise err
            return flight.get("result")
        finally:
            _release_lock(r, lock_key, token)
    try:
        result = fn()
        flight["result"] = result
        try:
            r.set(res_key, _pack_ok(result), ex=max(2, ttl))
        except Exception:
            pass
        return result
    except Exception as exc:
        flight["error"] = exc
        try:
            r.set(res_key, _pack_err(), ex=max(2, min(30, ttl)))
        except Exception:
            pass
        raise
    finally:
        flight["ev"].set()
        with _FLIGHT_LOCK:
            _FLIGHTS.pop(key, None)
        _release_lock(r, lock_key, token)


def singleflight(key: str, fn: Callable[[], _T], *, wait_s: float = 90.0) -> _T | None:
    """One in-flight Google Ads call per key across workers (Redis SET NX EX).

    Winner calls fn, writes a short-lived result blob, then releases the lock.
    Waiters poll the result blob and do not call fn. Redis down → in-memory.
    """
    k = str(key or "").strip()
    if not k:
        return fn()

    with _FLIGHT_LOCK:
        existing = _FLIGHTS.get(k)
    if existing is not None:
        existing["ev"].wait(timeout=wait_s)
        err = existing.get("error")
        if err is not None:
            raise err
        return existing.get("result")

    r = None
    try:
        r = _redis_client()
    except Exception:
        r = None
    if r is None:
        return _singleflight_memory(k, fn, wait_s=wait_s)

    ttl = _sf_ttl_s(wait_s)
    lock_key = _sf_lock_key(k)
    token = uuid.uuid4().hex
    try:
        acquired = bool(r.set(lock_key, token, nx=True, ex=ttl))
    except Exception:
        _LOG.warning("google_ads_singleflight_redis_unavailable")
        return _singleflight_memory(k, fn, wait_s=wait_s)

    deadline = time.monotonic() + max(0.5, float(wait_s or 90.0))
    if acquired:
        return _run_winner(k, fn, r, lock_key, token, ttl, wait_s)

    res_key = _sf_result_key(k)
    while time.monotonic() < deadline:
        try:
            packed = _unpack_result(r.get(res_key))
        except Exception:
            packed = None
        if packed is not None:
            kind, val = packed
            return None if kind == "err" else val
        try:
            locked = bool(r.exists(lock_key))
        except Exception:
            locked = False
        if not locked:
            try:
                packed = _unpack_result(r.get(res_key))
            except Exception:
                packed = None
            if packed is not None:
                kind, val = packed
                return None if kind == "err" else val
            steal = uuid.uuid4().hex
            try:
                stole = bool(r.set(lock_key, steal, nx=True, ex=ttl))
            except Exception:
                remaining = max(0.2, deadline - time.monotonic())
                return _singleflight_memory(k, fn, wait_s=remaining)
            if stole:
                return _run_winner(k, fn, r, lock_key, steal, ttl, wait_s)
        time.sleep(_SF_POLL_S)
    return None


def _month_num(month_val: Any) -> int | None:
    if month_val is None:
        return None
    raw_name = getattr(month_val, "name", None)
    if callable(raw_name):
        try:
            raw_name = raw_name()
        except TypeError:
            raw_name = None
    if raw_name:
        token = str(raw_name).upper().split(".")[-1]
        if token in _MONTH_NAME_TO_NUM:
            return _MONTH_NAME_TO_NUM[token]
    token = str(month_val).upper().split(".")[-1]
    if token in _MONTH_NAME_TO_NUM:
        return _MONTH_NAME_TO_NUM[token]
    try:
        n = int(month_val)
    except (TypeError, ValueError):
        return None
    if 1 <= n <= 12:
        return n
    # MonthOfYear proto: UNSPECIFIED=0 UNKNOWN=1 JANUARY=2 … DECEMBER=13
    if n == 13:
        return 12
    if 2 <= n <= 13:
        return n - 1
    return None


def _comp_label(comp: Any) -> str:
    if comp is None or comp == "":
        return ""
    raw = getattr(comp, "name", None)
    if not raw:
        raw = comp
    token = str(raw).upper().split(".")[-1].strip()
    if token in ("LOW", "MEDIUM", "HIGH"):
        return token
    return ""


def _monthly_from_metrics(metrics: Any) -> list[dict[str, int]]:
    out: list[dict[str, int]] = []
    vols = (
        getattr(metrics, "monthly_search_volumes", None)
        or getattr(metrics, "monthly_searches", None)
        or []
    )
    for item in vols:
        if isinstance(item, dict):
            year_raw, month_raw = item.get("year"), item.get("month")
            sv_raw = item.get("search_volume", item.get("monthly_searches"))
        else:
            year_raw = getattr(item, "year", None)
            month_raw = getattr(item, "month", None)
            sv_raw = getattr(item, "monthly_searches", None)
            if sv_raw is None:
                sv_raw = getattr(item, "search_volume", None)
        year = _as_int(year_raw) or 0
        mo = _month_num(month_raw)
        sv = _as_int(sv_raw)
        if sv is None:
            sv = 0
        if year <= 0 or not mo:
            continue
        out.append({"year": year, "month": mo, "search_volume": max(0, sv)})
    return out


def _row_from_metrics(keyword: str, metrics: Any) -> dict[str, Any]:
    vol = (
        _as_int(getattr(metrics, "avg_monthly_searches", None))
        or _as_int(getattr(metrics, "average_monthly_searches", None))
        or 0
    )
    comp_name = _comp_label(getattr(metrics, "competition", None))
    cidx = _as_int(getattr(metrics, "competition_index", None))
    cpc_lo = _micros_to_currency(getattr(metrics, "low_top_of_page_bid_micros", None))
    cpc_hi = _micros_to_currency(getattr(metrics, "high_top_of_page_bid_micros", None))
    cpc_avg = _micros_to_currency(getattr(metrics, "average_cpc_micros", None))
    if cpc_avg <= 0 and (cpc_lo > 0 or cpc_hi > 0):
        vals = [x for x in (cpc_lo, cpc_hi) if x > 0]
        cpc_avg = round(sum(vals) / len(vals), 4) if vals else 0.0
    monthly = _monthly_from_metrics(metrics)
    has_cpc = cpc_avg > 0 or cpc_lo > 0 or cpc_hi > 0
    return {
        "keyword": keyword,
        "search_volume": vol,
        "cpc_avg": cpc_avg,
        "cpc_min": cpc_lo if cpc_lo > 0 else cpc_avg,
        "cpc_max": cpc_hi if cpc_hi > 0 else cpc_avg,
        "cpc_source": "google_ads" if has_cpc else "",
        "competition": comp_name,
        "competition_index": cidx if cidx is not None else (comp_name or None),
        "competition_source": "google_ads" if comp_name else "",
        "monthly_searches": monthly,
        "monthly_source": "google_ads" if monthly else "",
        "volume_source": "google_ads",
        "provider": "google_ads",
        "confidence": 0.95,
        "currency": "VND",
    }


def _volume_enabled() -> bool:
    return os.getenv("VOLUME_API_ENABLED", "0").lower() in ("1", "true", "yes")


def fetch_google_ads_keyword_ideas(
    seeds: list[str],
    *,
    country: str | None,
    language: str | None,
    limit: int = 80,
) -> list[dict[str, Any]]:
    if not _volume_enabled() or not google_ads_configured():
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for k in seeds or []:
        s = str(k or "").strip()
        if not s or len(s) > 200:
            continue
        low = s.lower()
        if low in seen:
            continue
        seen.add(low)
        cleaned.append(s)
    if not cleaned:
        return []

    client = _get_client()
    if client is None:
        return []
    customer_id = _digits(_env("GOOGLE_ADS_CUSTOMER_ID"))
    geo, lang = geo_language_ids(country=country, language=language)
    cap = max(5, min(int(limit or 80), 700))

    def _run() -> list[dict[str, Any]]:
        idea_service = client.get_service("KeywordPlanIdeaService")
        google_ads_service = client.get_service("GoogleAdsService")
        geo_service = client.get_service("GeoTargetConstantService")
        request = client.get_type("GenerateKeywordIdeasRequest")
        request.customer_id = customer_id
        request.language = google_ads_service.language_constant_path(lang)
        request.geo_target_constants.append(geo_service.geo_target_constant_path(geo))
        request.include_adult_keywords = False
        request.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
        for s in cleaned:
            request.keyword_seed.keywords.append(s)
        rows: list[dict[str, Any]] = []
        seen_kw: set[str] = set()
        for idea in idea_service.generate_keyword_ideas(request=request, timeout=_timeout_s()):
            kw = str(getattr(idea, "text", "") or "").strip()
            if not kw:
                continue
            low = kw.lower()
            if low in seen_kw:
                continue
            seen_kw.add(low)
            rows.append(_row_from_metrics(kw, idea.keyword_idea_metrics))
            if len(rows) >= cap:
                break
        return rows

    try:
        return _call_with_retry(_run, label="ideas")
    except Exception as exc:
        if type(exc).__name__ == "RefreshError":
            _reset_client()
        _LOG.warning("google_ads_ideas_fail code=%s request_id=%s", _error_code_name(exc), _request_id(exc) or "-")
        return []


def fetch_google_ads_historical_metrics(
    keywords: list[str],
    *,
    country: str | None,
    language: str | None,
) -> list[dict[str, Any]]:
    if not _volume_enabled() or not google_ads_configured():
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for k in keywords or []:
        s = str(k or "").strip()
        if not s or len(s) > 200:
            continue
        low = s.lower()
        if low in seen:
            continue
        seen.add(low)
        cleaned.append(s)
    if not cleaned:
        return []

    client = _get_client()
    if client is None:
        return []
    customer_id = _digits(_env("GOOGLE_ADS_CUSTOMER_ID"))
    geo, lang = geo_language_ids(country=country, language=language)

    def _run() -> list[dict[str, Any]]:
        idea_service = client.get_service("KeywordPlanIdeaService")
        google_ads_service = client.get_service("GoogleAdsService")
        geo_service = client.get_service("GeoTargetConstantService")
        request = client.get_type("GenerateKeywordHistoricalMetricsRequest")
        request.customer_id = customer_id
        request.keywords.extend(cleaned)
        request.language = google_ads_service.language_constant_path(lang)
        request.geo_target_constants.append(geo_service.geo_target_constant_path(geo))
        request.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
        request.include_adult_keywords = False
        resp = idea_service.generate_keyword_historical_metrics(request=request, timeout=_timeout_s())
        by_low: dict[str, dict[str, Any]] = {}
        for result in list(getattr(resp, "results", None) or []):
            metrics = getattr(result, "keyword_metrics", None)
            if metrics is None:
                continue
            names = [str(getattr(result, "text", "") or "").strip()]
            names.extend(str(x).strip() for x in list(getattr(result, "close_variants", None) or []))
            row_template = _row_from_metrics(names[0] if names else "", metrics)
            for name in names:
                if not name:
                    continue
                item = dict(row_template)
                item["keyword"] = name
                by_low[name.lower()] = item
        out: list[dict[str, Any]] = []
        for kw in cleaned:
            hit = by_low.get(kw.lower())
            if not hit:
                continue
            row = dict(hit)
            row["keyword"] = kw
            out.append(row)
        return out

    try:
        return _call_with_retry(_run, label="metrics")
    except Exception as exc:
        if type(exc).__name__ == "RefreshError":
            _reset_client()
        _LOG.warning("google_ads_metrics_fail code=%s request_id=%s", _error_code_name(exc), _request_id(exc) or "-")
        return []
