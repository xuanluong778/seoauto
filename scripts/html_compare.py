"""Compare server HTML vs rendered DOM for SEO debugging (critical tags + deltas)."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from bs4 import BeautifulSoup

from app.services.canonical_utils import extract_declared_canonical_href
from app.services.seo_normalize import normalize_canonical, normalize_text


def _sha256_short(text: str, n: int = 12) -> str:
    h = hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()
    return h[:n]


def _first_title(html: str) -> str:
    if not html or not isinstance(html, str):
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        t = soup.find("title")
        return normalize_text(t.get_text() if t else "")
    except Exception:
        m = re.search(r"<title[^>]*>([^<]*)</title>", html, re.I | re.DOTALL)
        return normalize_text(m.group(1) if m else "")


def _first_meta_description(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for name in ("description",):
        m = soup.find("meta", attrs={"name": name})
        if m and m.get("content") is not None:
            return normalize_text(m.get("content"))
    m = soup.find("meta", attrs={"property": "og:description"})
    if m and m.get("content") is not None:
        return normalize_text(m.get("content"))
    return ""


def _h1_texts(html: str) -> list[str]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out: list[str] = []
    for h in soup.find_all("h1"):
        t = normalize_text(h.get_text(" ", strip=True))
        if t:
            out.append(t)
    return out


def _canonical_normalized(html: str, base_url: str) -> str:
    href = extract_declared_canonical_href(html, base_url)
    if not href:
        return ""
    return normalize_canonical(href, base_url) or ""


def extract_critical_seo_snapshot(html: str, base_url: str) -> dict[str, Any]:
    return {
        "title": _first_title(html)[:500],
        "meta_description": _first_meta_description(html)[:800],
        "h1": _h1_texts(html)[:24],
        "canonical": _canonical_normalized(html, base_url),
    }


def _present_title(s: dict[str, Any]) -> bool:
    return bool((s.get("title") or "").strip())


def _present_meta(s: dict[str, Any]) -> bool:
    return bool((s.get("meta_description") or "").strip())


def _present_h1(s: dict[str, Any]) -> bool:
    return bool(s.get("h1"))


def _present_canonical(s: dict[str, Any]) -> bool:
    return bool((s.get("canonical") or "").strip())


def _diff_critical_presence(raw_s: dict[str, Any], ren_s: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Elements meaningful in rendered but absent in raw, and vice versa."""
    checks = (
        ("title", _present_title, "title"),
        ("meta_description", _present_meta, "meta_description"),
        ("H1", _present_h1, "h1"),
        ("canonical", _present_canonical, "canonical"),
    )
    missing_in_raw: list[str] = []
    missing_in_rendered: list[str] = []
    for label, pred, _key in checks:
        pr, pe = pred(raw_s), pred(ren_s)
        if pe and not pr:
            missing_in_raw.append(label)
        if pr and not pe:
            missing_in_rendered.append(label)
    return missing_in_raw, missing_in_rendered


def build_html_comparison(
    raw_html: str,
    rendered_html: str,
    *,
    raw_final_url: str = "",
    rendered_final_url: str = "",
) -> dict[str, Any]:
    raw = (raw_html or "").replace("\r\n", "\n").replace("\r", "\n")
    ren = (rendered_html or "").replace("\r\n", "\n").replace("\r", "\n")
    identical = raw == ren
    len_r, len_e = len(raw), len(ren)
    if len_r > 0:
        content_length_ratio = round(len_e / len_r, 4)
    else:
        content_length_ratio = 1.0 if len_e == 0 else 999.0

    ru = (raw_final_url or "").strip()
    eu = (rendered_final_url or "").strip()
    urls_match = bool(ru and eu and ru == eu)

    raw_snap = extract_critical_seo_snapshot(raw, ru or eu)
    ren_snap = extract_critical_seo_snapshot(ren, eu or ru)

    tr, te = raw_snap["title"], ren_snap["title"]
    title_match = (tr == te) if (tr or te) else True

    missing_in_raw, missing_in_rendered = _diff_critical_presence(raw_snap, ren_snap)

    js_likely_changed_dom = bool(
        not identical
        and (
            len_e != len_r
            or not title_match
            or bool(missing_in_raw) or bool(missing_in_rendered)
            or (raw_snap["canonical"] != ren_snap["canonical"] and (raw_snap["canonical"] or ren_snap["canonical"]))
        )
    )

    return {
        "identical": identical,
        "title_match": title_match,
        "content_length_ratio": float(content_length_ratio),
        "js_likely_changed_dom": js_likely_changed_dom,
        "missing_elements_in_raw": missing_in_raw,
        "missing_elements_in_rendered": missing_in_rendered,
        "raw_length": len_r,
        "rendered_length": len_e,
        "length_delta": len_e - len_r,
        "raw_sha256_12": _sha256_short(raw),
        "rendered_sha256_12": _sha256_short(ren),
        "raw_final_url": ru,
        "rendered_final_url": eu,
        "urls_match": urls_match,
        "title_raw": tr[:300],
        "title_rendered": te[:300],
        "meta_description_raw": (raw_snap["meta_description"] or "")[:400],
        "meta_description_rendered": (ren_snap["meta_description"] or "")[:400],
        "h1_raw": raw_snap["h1"][:8],
        "h1_rendered": ren_snap["h1"][:8],
        "canonical_raw_normalized": raw_snap["canonical"] or "",
        "canonical_rendered_normalized": ren_snap["canonical"] or "",
    }


def summarize_raw_vs_rendered(
    raw_html: str,
    rendered_html: str,
    *,
    raw_final_url: str = "",
    rendered_final_url: str = "",
) -> dict[str, Any]:
    """Backward-compatible name; returns full advanced comparison."""
    return build_html_comparison(
        raw_html,
        rendered_html,
        raw_final_url=raw_final_url,
        rendered_final_url=rendered_final_url,
    )
