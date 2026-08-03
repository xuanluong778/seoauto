"""
Fetch top organic URLs for a query (Google CSE, SerpAPI, or custom JSON endpoint).

URLs are normalized + deduplicated for stable overlap / caching.
Supports locale (country, language), device (desktop/mobile), daily disk snapshots,
retries with optional HTTP proxy, and fallback custom endpoint.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests

_LOG = logging.getLogger(__name__)

_MEM_SERP: dict[str, dict[str, Any]] = {}

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def normalize_serp_url(url: str) -> str:
    """Strip fragment, common tracking params, normalize scheme/host/path for dedupe."""
    try:
        p = urlparse((url or "").strip())
        # Normalize protocol to HTTPS for stable dedupe/cache keys.
        scheme = "https"
        netloc = (p.netloc or "").lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        path = (p.path or "/").rstrip("/") or "/"
        q = parse_qs(p.query, keep_blank_values=True)
        drop = frozenset(
            (
                "utm_source",
                "utm_medium",
                "utm_campaign",
                "utm_term",
                "utm_content",
                "utm_id",
                "utm_name",
                "gclid",
                "fbclid",
                "msclkid",
                "ttclid",
                "twclid",
                "yclid",
                "dclid",
                "_hsenc",
                "_hsmi",
                "igshid",
                "ref",
                "ref_src",
                "vero_id",
                "mc_cid",
                "mc_eid",
            )
        )
        q = {k: v for k, v in q.items() if k.lower() not in drop}
        query = urlencode(sorted((k, v[0]) for k, v in q.items() if v), doseq=True)
        return urlunparse((scheme, netloc, path, "", query, ""))
    except Exception:
        return (url or "").strip().lower()


def normalize_serp_domain(host: str) -> str:
    h = (host or "").strip().lower()
    return h[4:] if h.startswith("www.") else h


def is_serp_noise_or_ad_url(url: str) -> bool:
    """
    Loại URL quảng cáo / rich feature không phải organic thường lọt qua CSE hoặc custom proxy.

    Dùng trước khi dedupe overlap clustering.
    """
    u = (url or "").strip().lower()
    if not u:
        return True
    try:
        p = urlparse(u)
        host = (p.netloc or "").lower()
        path_q = f"{p.path or ''}?{p.query or ''}".lower()
    except Exception:
        return True
    if host.startswith("www."):
        host = host[4:]
    bad_hosts = (
        "googleadservices.com",
        "pagead2.googlesyndication.com",
        "www.googleadservices.com",
        "googleads.g.doubleclick.net",
        "doubleclick.net",
        "www.doubleclick.net",
        "adservice.google.com",
        "tpc.googlesyndication.com",
        "www.googlesyndication.com",
    )
    if any(h in host for h in bad_hosts):
        return True
    if "googleadservices" in host or "googlesyndication" in host or "doubleclick" in host:
        return True
    needles = (
        "/aclk?",
        "adurl=",
        "/pagead/",
        "/ads/",
        "/ad/",
        "adclick.",
        "doubleclick.net",
        "gclid=",
        "dclid=",
    )
    if any(n in u for n in needles):
        return True
    # Shopping / paid surfaces (heuristic)
    if host == "shopping.google.com" or host.endswith(".shopping.google.com"):
        return True
    return False


def _is_low_quality_or_irrelevant(url: str, title: str = "", snippet: str = "") -> bool:
    """
    Heuristic filter for low-quality / irrelevant SERP pages.
    Keep conservative to avoid dropping legitimate organic results.
    """
    u = (url or "").strip().lower()
    t = (title or "").strip().lower()
    s = (snippet or "").strip().lower()
    if not u:
        return True
    try:
        p = urlparse(u)
        host = normalize_serp_domain(p.hostname or "")
        path = (p.path or "").lower()
        query = (p.query or "").lower()
    except Exception:
        return True

    # Non-HTML assets / downloads are rarely useful for keyword intent SERP.
    bad_ext = (
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".svg",
        ".pdf",
        ".mp4",
        ".mp3",
        ".zip",
        ".rar",
        ".7z",
        ".exe",
        ".dmg",
    )
    if any(path.endswith(ext) for ext in bad_ext):
        return True

    # Search/tag/archive/profile pages are often thin and noisy for SERP overlap.
    if "/search" in path or "/tag/" in path or "/tags/" in path or "/author/" in path:
        return True
    if "?" in u and ("?s=" in u or "&s=" in u):
        return True

    # Proxy/cache/translate wrappers.
    if "webcache.googleusercontent.com" in host or "translate.google." in host:
        return True

    low_hosts = (
        "pinterest.com",
        "m.pinterest.com",
        "webcache.googleusercontent.com",
    )
    if host in low_hosts:
        return True

    # Soft relevance check when both title/snippet are empty and URL path is very weak.
    if not t and not s and (path in ("", "/") or len(path) < 2):
        return True
    return False


def _title_token_set(text: str) -> set[str]:
    s = re.sub(r"[^a-z0-9\u00C0-\u024F]+", " ", (text or "").lower()).strip()
    toks = [t for t in s.split() if len(t) >= 2]
    stop = {
        "the",
        "and",
        "for",
        "with",
        "this",
        "that",
        "cach",
        "nhung",
        "cua",
        "la",
        "va",
        "cho",
        "tu",
        "seo",
    }
    return {t for t in toks if t not in stop}


def _title_similarity_jaccard(a: str, b: str) -> float:
    sa = _title_token_set(a)
    sb = _title_token_set(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    if inter <= 0:
        return 0.0
    union = len(sa | sb)
    return (inter / union) if union else 0.0


def _classify_serp_page_intent(url: str, title: str = "") -> str:
    u = (url or "").lower()
    t = (title or "").lower()
    try:
        p = urlparse(u)
        path = (p.path or "").lower()
    except Exception:
        path = ""
    if any(k in path for k in ("/product", "/products", "/shop", "/cart", "/checkout", "/san-pham", "/mua-")):
        return "transactional"
    if any(k in path for k in ("/category", "/categories", "/collections", "/danh-muc")):
        return "commercial"
    if any(k in path for k in ("/blog", "/post", "/article", "/news", "/tin-tuc", "/huong-dan")):
        return "informational"
    if any(k in path for k in ("/login", "/signin", "/register", "/signup")):
        return "navigational"
    if any(k in t for k in ("buy", "price", "mua", "gia", "đặt", "đặt mua")):
        return "transactional"
    if any(k in t for k in ("review", "vs", "top", "best", "so sánh", "đánh giá")):
        return "commercial"
    return "informational"


def _norm_device(device: str | None) -> str:
    d = (device or "desktop").strip().lower()
    if d in ("m", "mobile", "phone"):
        return "mobile"
    return "desktop"


def _norm_country(country: str | None) -> str:
    c = (country or os.getenv("SERP_DEFAULT_COUNTRY", "vn")).strip().lower()
    if len(c) == 2:
        return c
    m = {
        "vietnam": "vn",
        "united states": "us",
        "usa": "us",
        "united kingdom": "gb",
        "uk": "gb",
    }
    return m.get(c, c[:2] if len(c) >= 2 else "vn")


def _norm_language(language: str | None) -> str:
    lang = (language or os.getenv("SERP_DEFAULT_LANGUAGE", "vi")).strip().lower()
    return lang[:5] if lang else "vi"


def _resolved_locale(
    *,
    country: str | None,
    language: str | None,
    device: str | None,
) -> dict[str, str]:
    return {
        "country": _norm_country(country),
        "language": _norm_language(language),
        "device": _norm_device(device),
    }


def _serp_cache_digest(keyword: str, locale: dict[str, str]) -> str:
    raw = "|".join(
        [
            (keyword or "").strip().lower(),
            locale["country"],
            locale["language"],
            locale["device"],
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_key(keyword: str) -> str:
    """Legacy digest (keyword only) — kept for imports/tests; prefer :func:`_serp_cache_digest`."""
    return hashlib.sha256(keyword.strip().lower().encode("utf-8")).hexdigest()


def _dedupe_serp_lists(
    urls: list[str],
    titles: list[str],
    snippets: list[str],
    *,
    max_keep: int | None = None,
    unique_domain: bool = True,
) -> tuple[list[str], list[str], list[str]]:
    seen: set[str] = set()
    seen_domains: set[str] = set()
    uo: list[str] = []
    to: list[str] = []
    so: list[str] = []
    title_sim_thr = max(0.45, min(0.98, float(os.getenv("SERP_TITLE_SIMILARITY_THRESHOLD", "0.86"))))
    for i, raw in enumerate(urls):
        u = normalize_serp_url(str(raw or ""))
        ti = str(titles[i])[:200] if i < len(titles) else ""
        si = str(snippets[i])[:300] if i < len(snippets) else ""
        if not u or u in seen or is_serp_noise_or_ad_url(u) or _is_low_quality_or_irrelevant(u, ti, si):
            continue
        try:
            dom = normalize_serp_domain(urlparse(u).hostname or "")
        except Exception:
            dom = ""
        if unique_domain and dom and dom in seen_domains:
            continue
        # Near-duplicate content control via title similarity.
        if ti:
            is_near_dup = False
            for kept_title in to:
                if kept_title and _title_similarity_jaccard(ti, kept_title) >= title_sim_thr:
                    is_near_dup = True
                    break
            if is_near_dup:
                continue
        seen.add(u)
        if dom:
            seen_domains.add(dom)
        uo.append(u)
        to.append(ti)
        so.append(si)
        if max_keep is not None and len(uo) >= max(1, int(max_keep)):
            break
    return uo, to, so


def _ensure_min_valid_results(
    snap: dict[str, Any],
    *,
    locale: dict[str, str],
    min_valid: int,
    target_n: int,
) -> dict[str, Any]:
    """
    Try to guarantee 8-10 valid results by backfilling next result pages.
    """
    kw = str(snap.get("keyword") or "").strip()
    if not kw:
        return snap

    urls = list(snap.get("serp_urls") or [])
    titles = list(snap.get("titles") or [])
    snippets = list(snap.get("snippets") or [])

    u2, t2, s2 = _dedupe_serp_lists(urls, titles, snippets, max_keep=target_n, unique_domain=True)
    if len(u2) >= min_valid:
        snap["serp_urls"], snap["titles"], snap["snippets"] = u2, t2, s2
        return snap

    max_pages = max(0, min(8, int(os.getenv("SERP_BACKFILL_MAX_PAGES", "3"))))
    start = 11
    for _ in range(max_pages):
        page = fetch_serp_keyword_page(
            kw,
            start=start,
            num=10,
            use_cache=False,
            country=locale["country"],
            language=locale["language"],
            device=locale["device"],
        )
        start += 10
        if not page:
            continue
        urls.extend(list(page.get("serp_urls") or []))
        titles.extend(list(page.get("titles") or []))
        snippets.extend(list(page.get("snippets") or []))
        u2, t2, s2 = _dedupe_serp_lists(urls, titles, snippets, max_keep=target_n, unique_domain=True)
        if len(u2) >= min_valid:
            break

    snap["serp_urls"], snap["titles"], snap["snippets"] = u2, t2, s2
    return snap


def _serp_proxies() -> dict[str, str] | None:
    p = (os.getenv("HTTP_PROXY_SERP") or os.getenv("HTTPS_PROXY_SERP") or "").strip()
    if not p:
        return None
    return {"http": p, "https": p}


def _http_get_with_retries(url: str, *, params: dict[str, Any] | None = None, timeout: float = 30) -> requests.Response | None:
    proxies = _serp_proxies()
    retries = int(os.getenv("SERP_FETCH_RETRIES", "3"))
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout, proxies=proxies)
            if r.status_code in (429, 502, 503, 504):
                time.sleep(min(6.0, 0.9 * (2**attempt)))
                continue
            r.raise_for_status()
            return r
        except Exception as exc:
            _LOG.debug("HTTP GET attempt %s failed: %s", attempt, exc)
            time.sleep(min(4.0, 0.55 * (attempt + 1)))
    return None


def _http_post_with_retries(url: str, *, json_body: dict[str, Any], timeout: float = 35) -> requests.Response | None:
    proxies = _serp_proxies()
    retries = int(os.getenv("SERP_FETCH_RETRIES", "3"))
    for attempt in range(retries):
        try:
            r = requests.post(url, json=json_body, timeout=timeout, proxies=proxies)
            if r.status_code in (429, 502, 503, 504):
                time.sleep(min(6.0, 0.95 * (2**attempt)))
                continue
            r.raise_for_status()
            return r
        except Exception as exc:
            _LOG.debug("HTTP POST attempt %s failed: %s", attempt, exc)
            time.sleep(min(4.0, 0.6 * (attempt + 1)))
    return None


def _redis_get_v2(digest: str) -> dict[str, Any] | None:
    try:
        import redis

        r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"), decode_responses=True)
        raw = r.get(f"serp:v2:{digest}")
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return None


def _redis_set_v2(digest: str, payload: dict[str, Any]) -> None:
    try:
        import redis

        r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"), decode_responses=True)
        r.setex(f"serp:v2:{digest}", int(os.getenv("SERP_CACHE_TTL_SECONDS", "604800")), json.dumps(payload)[:120000])
    except Exception:
        pass


def _maybe_persist_serp_snapshot(snap: dict[str, Any], locale: dict[str, str]) -> None:
    if os.getenv("SERP_SNAPSHOT_DISK", "1").lower() not in ("1", "true", "yes"):
        return
    try:
        day = date.today().isoformat()
        root = _PROJECT_ROOT / "data" / "serp_snapshots" / day
        root.mkdir(parents=True, exist_ok=True)
        digest = _serp_cache_digest(str(snap.get("keyword") or ""), locale)
        path = root / f"{digest[:40]}.json"
        out = {
            **snap,
            "locale": dict(locale),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        path.write_text(json.dumps(out, ensure_ascii=False)[:200000], encoding="utf-8")
    except Exception as exc:
        _LOG.debug("SERP disk snapshot skipped: %s", exc)


def _finalize_snap(snap: dict[str, Any], *, locale: dict[str, str]) -> dict[str, Any]:
    urls = list(snap.get("serp_urls") or [])
    titles = list(snap.get("titles") or [])
    snippets = list(snap.get("snippets") or [])
    features = snap.get("features")
    keep_n = max(1, min(10, int(snap.get("top_n") or 10)))
    u2, t2, s2 = _dedupe_serp_lists(urls, titles, snippets, max_keep=keep_n, unique_domain=True)
    digest = _serp_cache_digest(str(snap.get("keyword") or ""), locale)
    out = {
        "keyword": snap.get("keyword") or "",
        "serp_urls": u2,
        "titles": t2,
        "snippets": s2,
        "features": features if isinstance(features, (dict, list)) else {},
        "source": snap.get("source") or "none",
        "country": locale["country"],
        "language": locale["language"],
        "device": locale["device"],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "serp_cache_digest": digest,
    }
    doms = []
    for u in u2:
        try:
            doms.append(normalize_serp_domain(urlparse(u).hostname or ""))
        except Exception:
            doms.append("")
    out["domains"] = doms
    # SERP consistency / ambiguity flags for downstream ranking logic.
    intents = [_classify_serp_page_intent(u2[i], t2[i] if i < len(t2) else "") for i in range(len(u2))]
    ic: dict[str, int] = {}
    for it in intents:
        ic[it] = ic.get(it, 0) + 1
    total = max(1, len(intents))
    shares = {k: (v / total) for k, v in ic.items()}
    top2 = sorted(shares.items(), key=lambda kv: kv[1], reverse=True)[:2]
    mixed_blog_product = ("informational" in shares and ("transactional" in shares or "commercial" in shares))
    mixed = (
        (len(top2) >= 2 and top2[0][1] < 0.62 and top2[1][1] >= 0.28)
        or mixed_blog_product
    )
    out["serp_consistency"] = {
        "intent_distribution": {k: round(v, 4) for k, v in shares.items()},
        "mixed_intent": bool(mixed),
    }
    out["ambiguous_keyword"] = bool(mixed)
    feats_obj = out["features"] if isinstance(out.get("features"), dict) else {}
    feats_obj["serp_quality"] = {
        "valid_result_count": len(u2),
        "target_result_count": keep_n,
        "mixed_intent": bool(mixed),
        "ambiguous_keyword": bool(mixed),
    }
    out["features"] = feats_obj
    return out


def _fetch_google_cse(keyword: str, *, top_n: int, locale: dict[str, str]) -> dict[str, Any] | None:
    api_key = (os.getenv("GOOGLE_CSE_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    cx = (os.getenv("GOOGLE_CSE_ID") or os.getenv("GOOGLE_CSE_CX") or "").strip()
    if not api_key or not cx:
        return None
    params: dict[str, Any] = {
        "key": api_key,
        "cx": cx,
        "q": keyword,
        "num": min(10, top_n),
        "hl": locale["language"],
        "gl": locale["country"],
    }
    url = "https://www.googleapis.com/customsearch/v1"
    r = _http_get_with_retries(url, params=params, timeout=25)
    if r is None:
        return None
    try:
        data = r.json()
        items = data.get("items") or []
        urls: list[str] = []
        titles: list[str] = []
        snippets: list[str] = []
        for it in items[:top_n]:
            u = normalize_serp_url(str(it.get("link") or ""))
            if u and u not in urls:
                urls.append(u)
            titles.append(str(it.get("title") or "")[:200])
            snippets.append(str(it.get("snippet") or "")[:300])
        return {"keyword": keyword, "serp_urls": urls, "titles": titles, "snippets": snippets, "source": "google_cse"}
    except Exception as exc:
        _LOG.debug("CSE parse failed: %s", exc)
        return None


def _fetch_serpapi(keyword: str, *, top_n: int, locale: dict[str, str]) -> dict[str, Any] | None:
    api_key = (os.getenv("SERPAPI_KEY") or "").strip()
    if not api_key:
        return None
    url = "https://serpapi.com/search.json"
    params: dict[str, Any] = {
        "api_key": api_key,
        "q": keyword,
        "engine": "google",
        "num": min(10, top_n),
        "hl": locale["language"],
        "gl": locale["country"],
        "device": locale["device"],
    }
    gd = (os.getenv("SERPAPI_GOOGLE_DOMAIN") or "").strip()
    if gd:
        params["google_domain"] = gd
    r = _http_get_with_retries(url, params=params, timeout=30)
    if r is None:
        return None
    try:
        data = r.json()
        org = data.get("organic_results") or []
        urls: list[str] = []
        titles: list[str] = []
        snippets: list[str] = []
        for it in org[:top_n]:
            u = normalize_serp_url(str(it.get("link") or it.get("url") or ""))
            if u and u not in urls:
                urls.append(u)
            titles.append(str(it.get("title") or "")[:200])
            snippets.append(str(it.get("snippet") or "")[:300])
        # Surface-level SERP features (best-effort).
        feats: dict[str, Any] = {}
        for k in (
            "answer_box",
            "knowledge_graph",
            "top_stories",
            "news_results",
            "video_results",
            "videos",
            "people_also_ask",
            "related_questions",
            "local_results",
            "images_results",
            "shopping_results",
            "related_searches",
        ):
            if k in data:
                feats[k] = data.get(k)
        return {
            "keyword": keyword,
            "serp_urls": urls,
            "titles": titles,
            "snippets": snippets,
            "features": feats,
            "source": "serpapi",
        }
    except Exception as exc:
        _LOG.debug("SerpAPI parse failed: %s", exc)
        return None


def _fetch_custom_endpoint(url: str, keyword: str, *, top_n: int, locale: dict[str, str]) -> dict[str, Any] | None:
    if not url.strip():
        return None
    body = {
        "keyword": keyword,
        "top_n": top_n,
        "country": locale["country"],
        "language": locale["language"],
        "device": locale["device"],
    }
    r = _http_post_with_retries(url, json_body=body, timeout=35)
    if r is None:
        return None
    try:
        data = r.json()
        raw_urls = data.get("urls") or data.get("serp_urls") or []
        urls = [normalize_serp_url(str(u)) for u in raw_urls]
        urls = [u for u in urls if u][:top_n]
        titles = list(data.get("titles") or [])[:top_n]
        snippets = list(data.get("snippets") or [])[:top_n]
        feats = data.get("features")
        return {
            "keyword": keyword,
            "serp_urls": urls,
            "titles": titles,
            "snippets": snippets,
            "features": feats if isinstance(feats, (dict, list)) else {},
            "source": "custom",
        }
    except Exception as exc:
        _LOG.debug("Custom SERP endpoint failed: %s", exc)
        return None


def _snap_has_urls(s: dict[str, Any] | None) -> bool:
    return bool(s) and bool(s.get("serp_urls"))


def _fetch_dataforseo(keyword: str, *, top_n: int, locale: dict[str, str]) -> dict[str, Any] | None:
    """DataForSEO Google Organic Live Advanced — primary SERP provider when configured."""
    try:
        from app.services import dataforseo_client

        if not dataforseo_client.is_dataforseo_enabled() or dataforseo_client.get_basic_auth() is None:
            return None
    except Exception:
        return None

    loc_name = (os.getenv("DATAFORSEO_LOCATION_NAME") or "").strip()
    if not loc_name:
        loc_name = {
            "vn": "Vietnam",
            "us": "United States",
            "gb": "United Kingdom",
        }.get(locale["country"], "Vietnam")

    lang_name = (os.getenv("DATAFORSEO_LANGUAGE_NAME") or "").strip()
    if not lang_name:
        lang_name = {
            "vi": "Vietnamese",
            "en": "English",
        }.get(locale["language"][:2], "Vietnamese")

    depth = max(10, min(100, int(top_n or 10) + 5))
    res = dataforseo_client.google_serp_live_advanced(
        keyword,
        location_name=loc_name,
        language_name=lang_name,
        device=locale["device"],
        depth=depth,
    )
    if res.get("mock") and res.get("fallback_mock"):
        return None

    items = res.get("items") or []
    urls: list[str] = []
    titles: list[str] = []
    snippets: list[str] = []
    for it in items:
        if str(it.get("type") or "").lower() != "organic":
            continue
        u = normalize_serp_url(str(it.get("url") or ""))
        if not u or u in urls:
            continue
        urls.append(u)
        titles.append(str(it.get("title") or "")[:200])
        snippets.append(str(it.get("description") or it.get("snippet") or "")[:300])
        if len(urls) >= top_n:
            break

    if not urls:
        return None

    return {
        "keyword": keyword,
        "serp_urls": urls[:top_n],
        "titles": titles[:top_n],
        "snippets": snippets[:top_n],
        "features": {},
        "source": "dataforseo",
    }


def _fetch_chain(keyword: str, *, top_n: int, locale: dict[str, str]) -> dict[str, Any] | None:
    primary = (os.getenv("SERP_PROXY_URL") or "").strip()
    fallback = (os.getenv("SERP_FALLBACK_PROXY_URL") or "").strip()
    order = (os.getenv("SERP_FETCH_PROVIDER_ORDER", "custom,serpapi,cse") or "custom,serpapi,cse").lower()
    parts = [p.strip() for p in order.split(",") if p.strip()]

    def try_custom(u: str) -> dict[str, Any] | None:
        return _fetch_custom_endpoint(u, keyword, top_n=top_n, locale=locale)

    for prov in parts:
        cand: dict[str, Any] | None = None
        if prov == "dataforseo":
            cand = _fetch_dataforseo(keyword, top_n=top_n, locale=locale)
        elif prov == "custom" and primary:
            cand = try_custom(primary)
        elif prov == "serpapi":
            cand = _fetch_serpapi(keyword, top_n=top_n, locale=locale)
        elif prov in ("cse", "google_cse", "google"):
            cand = _fetch_google_cse(keyword, top_n=top_n, locale=locale)
        if _snap_has_urls(cand):
            return cand

    if fallback and fallback != primary:
        cand = try_custom(fallback)
        if _snap_has_urls(cand):
            return cand

    cand = try_custom(primary) if primary else None
    if _snap_has_urls(cand):
        return cand
    cand = _fetch_serpapi(keyword, top_n=top_n, locale=locale)
    if _snap_has_urls(cand):
        return cand
    return _fetch_google_cse(keyword, top_n=top_n, locale=locale)


def fetch_serp_keyword_page(
    keyword: str,
    *,
    start: int = 1,
    num: int = 10,
    use_cache: bool = False,
    country: str | None = None,
    language: str | None = None,
    device: str | None = None,
) -> dict[str, Any] | None:
    """
    Single page of organic results (1-based ``start`` like Google CSE).

    Used by ground-truth collector for depth up to ~100. Not merged into the short
    ``fetch_serp_for_keyword`` memory cache key (different slice).
    """
    kw = (keyword or "").strip()
    if not kw:
        return None
    num = max(1, min(10, num))
    start = max(1, start)
    loc = _resolved_locale(country=country, language=language, device=device)

    api_key = (os.getenv("SERPAPI_KEY") or "").strip()
    if api_key:
        url = "https://serpapi.com/search.json"
        serp_start = max(0, start - 1)
        params: dict[str, Any] = {
            "api_key": api_key,
            "q": kw,
            "engine": "google",
            "num": num,
            "start": serp_start,
            "hl": loc["language"],
            "gl": loc["country"],
            "device": loc["device"],
        }
        gd = (os.getenv("SERPAPI_GOOGLE_DOMAIN") or "").strip()
        if gd:
            params["google_domain"] = gd
        r = _http_get_with_retries(url, params=params, timeout=30)
        if r is not None:
            try:
                data = r.json()
                org = data.get("organic_results") or []
                urls: list[str] = []
                titles: list[str] = []
                snippets: list[str] = []
                for it in org[:num]:
                    u = normalize_serp_url(str(it.get("link") or it.get("url") or ""))
                    if u and u not in urls:
                        urls.append(u)
                    titles.append(str(it.get("title") or "")[:200])
                    snippets.append(str(it.get("snippet") or "")[:300])
                return {
                    "keyword": kw,
                    "serp_urls": urls,
                    "titles": titles,
                    "snippets": snippets,
                    "source": "serpapi",
                    "start": start,
                    "country": loc["country"],
                    "language": loc["language"],
                    "device": loc["device"],
                }
            except Exception as exc:
                _LOG.debug("SerpAPI page parse failed: %s", exc)

    gkey = (os.getenv("GOOGLE_CSE_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    cx = (os.getenv("GOOGLE_CSE_ID") or os.getenv("GOOGLE_CSE_CX") or "").strip()
    if gkey and cx:
        gurl = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": gkey,
            "cx": cx,
            "q": kw,
            "num": num,
            "start": start,
            "hl": loc["language"],
            "gl": loc["country"],
        }
        r = _http_get_with_retries(gurl, params=params, timeout=25)
        if r is not None:
            try:
                data = r.json()
                items = data.get("items") or []
                urls = []
                titles = []
                snippets = []
                for it in items[:num]:
                    u = normalize_serp_url(str(it.get("link") or ""))
                    if u and u not in urls:
                        urls.append(u)
                    titles.append(str(it.get("title") or "")[:200])
                    snippets.append(str(it.get("snippet") or "")[:300])
                return {
                    "keyword": kw,
                    "serp_urls": urls,
                    "titles": titles,
                    "snippets": snippets,
                    "source": "google_cse",
                    "start": start,
                    "country": loc["country"],
                    "language": loc["language"],
                    "device": loc["device"],
                }
            except Exception as exc:
                _LOG.debug("CSE page parse failed: %s", exc)

    return None


def fetch_serp_for_keyword(
    keyword: str,
    *,
    top_n: int = 10,
    use_cache: bool = True,
    country: str | None = None,
    language: str | None = None,
    device: str | None = None,
) -> dict[str, Any]:
    """
    Returns ``{keyword, serp_urls, titles, snippets, source, country, language, device, fetched_at, domains}``.

    ``country`` / ``language`` / ``device`` default from env ``SERP_DEFAULT_*`` when omitted.
    """
    kw = (keyword or "").strip()
    if not kw:
        return {"keyword": "", "serp_urls": [], "titles": [], "snippets": [], "source": "empty"}

    if os.getenv("SERP_FETCH_ENABLED", "0").lower() not in ("1", "true", "yes"):
        return {"keyword": kw, "serp_urls": [], "titles": [], "snippets": [], "features": {}, "source": "disabled"}

    loc = _resolved_locale(country=country, language=language, device=device)
    digest = _serp_cache_digest(kw, loc)

    if use_cache:
        hit = _redis_get_v2(digest)
        if hit and _snap_has_urls(hit):
            return hit
        if digest in _MEM_SERP and _snap_has_urls(_MEM_SERP[digest]):
            return _MEM_SERP[digest]

    raw = _fetch_chain(kw, top_n=top_n, locale=loc)
    if raw is None:
        snap = {"keyword": kw, "serp_urls": [], "titles": [], "snippets": [], "features": {}, "source": "none"}
    else:
        snap = raw
    # Improve quality and ensure minimum valid results where possible.
    min_valid = max(1, min(int(top_n), int(os.getenv("SERP_MIN_VALID_RESULTS", "8"))))
    target_n = max(min_valid, min(10, int(top_n)))
    snap["top_n"] = target_n
    snap = _ensure_min_valid_results(snap, locale=loc, min_valid=min_valid, target_n=target_n)
    snap = _finalize_snap(snap, locale=loc)
    _maybe_persist_serp_snapshot(snap, loc)

    if use_cache and _snap_has_urls(snap):
        _redis_set_v2(digest, snap)
        if len(_MEM_SERP) < int(os.getenv("SERP_MEMORY_CACHE_MAX", "500")):
            _MEM_SERP[digest] = snap
    return snap


def serp_top10_rows_from_snap(snap: dict[str, Any]) -> list[dict[str, str]]:
    """
    Compact SERP rows for storage in keyword research payloads.
    Output rows contain only: url, title, domain.
    """
    urls = list(snap.get("serp_urls") or [])
    titles = list(snap.get("titles") or [])
    out: list[dict[str, str]] = []
    for i, u in enumerate(urls[:10]):
        url = str(u or "").strip()
        if not url:
            continue
        try:
            dom = normalize_serp_domain(urlparse(url).hostname or "")
        except Exception:
            dom = ""
        out.append(
            {
                "url": url,
                "title": str(titles[i] if i < len(titles) else "")[:200],
                "domain": dom,
            }
        )
    return out


def fetch_serp_top10_rows(
    keyword: str,
    *,
    country: str | None = None,
    language: str | None = None,
    device: str | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """
    Fetch SERP top10 rows (url/title/domain) for one keyword.

    Returns payload:
    - keyword
    - rows: [{url,title,domain}...]
    - source, locale, serp_cache_digest, fetched_at (when available)
    """
    snap = fetch_serp_for_keyword(
        keyword,
        top_n=10,
        use_cache=use_cache,
        country=country,
        language=language,
        device=device,
    )
    return {
        "keyword": str(snap.get("keyword") or keyword or "").strip(),
        "rows": serp_top10_rows_from_snap(snap),
        "source": str(snap.get("source") or "none"),
        "locale": {
            "country": str(snap.get("country") or _norm_country(country)),
            "language": str(snap.get("language") or _norm_language(language)),
            "device": str(snap.get("device") or _norm_device(device)),
        },
        "serp_cache_digest": snap.get("serp_cache_digest"),
        "fetched_at": snap.get("fetched_at"),
    }


async def fetch_serp_for_keyword_async(
    keyword: str,
    *,
    top_n: int = 10,
    country: str | None = None,
    language: str | None = None,
    device: str | None = None,
) -> dict[str, Any]:
    """Async wrapper — passes locale/device through to :func:`fetch_serp_for_keyword`."""
    import asyncio

    return await asyncio.to_thread(
        fetch_serp_for_keyword,
        keyword,
        top_n=top_n,
        use_cache=True,
        country=country,
        language=language,
        device=device,
    )


def fetch_serp(
    keyword: str,
    *,
    location: str = "US",
    device: str = "desktop",
    num: int | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    """
    SERP payload shape used by ``serp_intel_bundle`` / competitor analysis.

    ``location`` is mapped to ``gl`` (2-letter when possible); ``device`` is passed to providers.
    """
    n = int(num) if num is not None else int(os.getenv("SERP_TOP_N", "10"))
    n = max(1, min(20, n))
    loc = (location or "US").strip().lower()
    country = loc[:2] if len(loc) == 2 else _norm_country(loc)
    lang = _norm_language(language or ("vi" if country == "vn" else "en"))
    snap = fetch_serp_for_keyword(keyword, top_n=n, use_cache=True, country=country, language=lang, device=device)
    urls = list(snap.get("serp_urls") or [])
    titles = list(snap.get("titles") or [])
    snippets = list(snap.get("snippets") or [])
    src = str(snap.get("source") or "none")
    serp_results: list[dict[str, Any]] = []
    for i, u in enumerate(urls):
        try:
            dom = normalize_serp_domain(urlparse(u).hostname or "")
        except Exception:
            dom = ""
        serp_results.append(
            {
                "position": i + 1,
                "url": u,
                "link": u,
                "title": titles[i] if i < len(titles) else "",
                "snippet": snippets[i] if i < len(snippets) else "",
                "domain": dom,
            }
        )
    fetch_error: str | None = None if urls else "no_organic_results"
    if not serp_results:
        kw = (keyword or "").strip()
        slug = hashlib.sha256(kw.encode("utf-8")).hexdigest()[:10]
        for i in range(n):
            u = f"https://example.com/mock-serp/{slug}/{i + 1}"
            serp_results.append(
                {
                    "position": i + 1,
                    "url": u,
                    "link": u,
                    "title": f"[mock {i + 1}] {kw}"[:200],
                    "snippet": "",
                    "domain": "example.com",
                }
            )
        src = "mock"
        fetch_error = None
    return {
        "keyword": (keyword or "").strip(),
        "serp_results": serp_results,
        "source": src,
        "location": location,
        "device": _norm_device(device),
        "language": lang,
        "country": country,
        "raw_api_extras": {},
        "fetch_error": fetch_error,
    }
