"""Strict URL normalization and exact matching for site: index checks."""

from __future__ import annotations

import html
import json
from urllib.parse import parse_qs, unquote, urlparse, urlunparse

_TRACKING_QUERY_KEYS = frozenset(
    {
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
    }
)
_LEAKED_QUERY_MARKERS = ("&amp;", "&safe=", "&sca_", "&hl=", "&pws=", "&sei=", "&emsg=", "&#", '"', "'")


def decode_url(url: str) -> str:
    try:
        return unquote(html.unescape((url or "").strip()))
    except Exception:
        return (url or "").strip()


def _unwrap_google_redirect(text: str) -> str:
    if text.startswith("/url?"):
        text = "https://www.google.com" + text
    try:
        parsed = urlparse(text)
        if "google." in (parsed.netloc or "") and parsed.path in ("/url", "/imgres"):
            q = parse_qs(parsed.query or "")
            for key in ("q", "url"):
                vals = q.get(key) or []
                if vals and str(vals[0]).startswith("http"):
                    return decode_url(str(vals[0]))
    except Exception:
        pass
    return text


def extract_google_href(href: str) -> str:
    text = decode_url((href or "").strip())
    if not text:
        return ""
    return _unwrap_google_redirect(text)


def sanitize_extracted_url(raw: str) -> str:
    """Clean href/cite pulled from Google HTML (strip leaked query junk)."""
    text = extract_google_href(raw)
    for marker in _LEAKED_QUERY_MARKERS:
        if marker in text:
            text = text.split(marker, 1)[0]
    return text.rstrip(".,);]\"'")


def is_leaked_query_echo(raw: str) -> bool:
    """True when URL text looks like the search query echoed in HTML, not an organic link."""
    text = (raw or "").strip().lower()
    if not text:
        return True
    return any(marker in text for marker in ("&safe=", "&sca_", "&pws=", "&sei=", "&emsg=", "sg_rel"))


def _strip_tracking_query(query: str) -> str:
    if not query:
        return ""
    q = parse_qs(query, keep_blank_values=True)
    kept = {k: v for k, v in q.items() if k.lower() not in _TRACKING_QUERY_KEYS}
    if not kept:
        return ""
    parts: list[str] = []
    for key in sorted(kept):
        for val in kept[key]:
            parts.append(f"{key}={val}")
    return "&".join(parts)


def normalize_index_url(url: str) -> str:
    """
    Normalize URL for strict index comparison.

  Rules:
    - lowercase host
    - drop scheme (http/https)
    - decode percent-encoding
    - strip only trailing slash at end of path (preserve internal /// segments)
    - drop fragment
    - drop common tracking query params
    """
    text = sanitize_extracted_url(decode_url((url or "").strip()))
    if not text:
        return ""
    try:
        parsed = urlparse(text)
    except Exception:
        return text.lower()

    host = (parsed.netloc or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]

    path = unquote(parsed.path or "")
    if not path:
        path = "/"
    elif path != "/":
        path = path.rstrip("/") or "/"

    query = _strip_tracking_query(parsed.query or "")
    key = host + path
    if query:
        key += "?" + query
    return key.lower()


def urls_exact_index_match(target: str, candidate: str) -> tuple[bool, str]:
    """
    Return (matched, match_type) where match_type is exact|canonical|none.

    Only exact normalized equality is accepted. Canonical is reserved for when
    both URLs normalize identically after stripping www on host only.
    """
    if not target or not candidate:
        return False, "none"

    cand = sanitize_extracted_url(candidate)
    if is_leaked_query_echo(candidate):
        return False, "none"

    target_key = normalize_index_url(target)
    candidate_key = normalize_index_url(cand)
    if not target_key or not candidate_key:
        return False, "none"

    if target_key == candidate_key:
        return True, "exact"

    # Allow www-only difference when path/query already match after www strip.
    try:
        tp, cp = urlparse(decode_url(target)), urlparse(cand)
        th = (tp.netloc or "").lower().removeprefix("www.")
        ch = (cp.netloc or "").lower().removeprefix("www.")
        if th == ch:
            tpath = unquote(tp.path or "/")
            cpath = unquote(cp.path or "/")
            if tpath != "/":
                tpath = tpath.rstrip("/") or "/"
            if cpath != "/":
                cpath = cpath.rstrip("/") or "/"
            tq = _strip_tracking_query(tp.query or "")
            cq = _strip_tracking_query(cp.query or "")
            if tpath == cpath and tq == cq:
                return True, "canonical"
    except Exception:
        pass

    return False, "none"


def urls_equivalent(target: str, candidate: str) -> bool:
    """Backward-compatible strict wrapper."""
    matched, _ = urls_exact_index_match(target, candidate)
    return matched


def build_match_evidence(
    *,
    query: str,
    target_url: str,
    candidate_urls: list[str],
    matched_url: str = "",
    match_type: str = "none",
    reason: str = "",
    extra: str = "",
) -> str:
    payload = {
        "query": query,
        "target_url_normalized": normalize_index_url(target_url),
        "candidate_urls": candidate_urls[:20],
        "matched_url": matched_url or None,
        "match_type": match_type,
        "reason": reason,
    }
    if extra:
        payload["detail"] = extra[:200]
    return json.dumps(payload, ensure_ascii=False)[:500]
