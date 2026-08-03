"""
Crawl quality scoring from a single page ``crawl_record`` (Playwright / HTTP bundle row).

Used to gate SEO pipeline noise and drive adaptive retries.
"""

from __future__ import annotations

import os
import re
from typing import Any

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore[misc, assignment]


def _parse_title_h1(html: str) -> tuple[bool, bool]:
    if not html or len(html.strip()) < 20:
        return False, False
    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(html, "html.parser")
            title = soup.find("title")
            h1 = soup.find("h1")
            has_title = bool(title and (title.string or "").strip())
            has_h1 = bool(h1 and h1.get_text(strip=True))
            return has_title, has_h1
        except Exception:
            pass
    low = html.lower()
    has_title = bool(re.search(r"<title[^>]*>[^<]+</title>", low, re.I))
    has_h1 = bool(re.search(r"<h1[\s>]", low, re.I))
    return has_title, has_h1


def _num(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def compute_crawl_quality(crawl_record: dict[str, Any]) -> dict[str, Any]:
    """
    Returns ``crawl_quality_score`` (0–1), ``quality_level``, ``reliability_flags``,
    and ``explain`` (list of {signal, impact, detail}) for debugging.
    """
    flags: list[str] = []
    explain: list[dict[str, Any]] = []
    score = 1.0

    def penalize(amount: float, flag: str, signal: str, detail: str) -> None:
        nonlocal score
        score += amount
        if flag and flag not in flags:
            flags.append(flag)
        explain.append({"signal": signal, "impact": round(amount, 4), "detail": detail[:400]})

    st = str(crawl_record.get("crawl_status") or "").lower()
    if st == "blocked":
        penalize(-0.75, "blocked", "crawl_status", "Crawl classified as blocked")
    elif st == "timeout":
        penalize(-0.55, "timeout", "crawl_status", "Navigation or render timed out")
    elif st and st != "success":
        penalize(-0.35, f"status_{st}", "crawl_status", f"Non-success crawl_status={st}")

    rs = str(crawl_record.get("render_status") or "").lower()
    rc = _num(crawl_record.get("render_confidence"))
    if rs == "partial" or rc < 0.45:
        penalize(-0.3, "partial_render", "render_status", f"render_status={rs} render_confidence={rc}")
    elif rc < 0.65:
        penalize(-0.12, "weak_render_confidence", "render_confidence", f"render_confidence={rc}")

    if crawl_record.get("js_dependency") is True:
        penalize(-0.15, "high_js_dependency", "js_dependency", "Heavy JS vs raw HTML delta")

    raw_vs = crawl_record.get("raw_vs_rendered") or {}
    if isinstance(raw_vs, dict):
        ratio = raw_vs.get("content_length_ratio")
        if ratio is not None and _num(ratio) > 3.5:
            penalize(-0.1, "raw_render_divergence", "raw_vs_rendered", f"content_length_ratio={ratio}")
        identical = raw_vs.get("identical")
        if identical is False and crawl_record.get("js_dependency") is not True:
            penalize(-0.05, "raw_render_mismatch", "raw_vs_rendered", "Rendered body differs from raw fetch")

    js_err = int(crawl_record.get("js_error_count") or 0)
    net_len = int(crawl_record.get("network_log_len") or 0)
    if js_err >= 5:
        penalize(-0.12, "many_js_errors", "network_errors", f"js_error_count={js_err}")
    elif js_err >= 2:
        penalize(-0.05, "some_js_errors", "network_errors", f"js_error_count={js_err}")
    if net_len >= 80:
        penalize(-0.06, "noisy_network", "network_errors", f"network_log_len={net_len}")

    html = str(crawl_record.get("html") or "")
    status = int(crawl_record.get("status") or 0)
    if status == 200 and html:
        has_title, has_h1 = _parse_title_h1(html)
        if not has_title:
            penalize(-0.12, "missing_title", "critical_elements", "No parseable <title>")
        if not has_h1:
            penalize(-0.08, "missing_h1", "critical_elements", "No <h1> in rendered HTML")
        lr = len(html)
        if lr < 400:
            penalize(-0.15, "tiny_html", "content_length", f"Rendered HTML length={lr}")
        elif lr < 1200:
            penalize(-0.06, "short_html", "content_length", f"Rendered HTML length={lr}")

    # Consistent positive signals
    if st == "success" and rs == "full" and rc >= 0.72 and crawl_record.get("js_dependency") is not True:
        penalize(0.06, "", "consistent_signals", "Stable full render, low JS delta")
    if st == "success" and status == 200 and html and crawl_record.get("js_dependency") is False:
        penalize(0.04, "", "consistent_signals", "200 + rendered HTML without JS dependency flag")

    score = max(0.0, min(1.0, score))

    if crawl_record.get("crawl_status") == "blocked" or "blocked" in flags:
        score = min(score, 0.28)
    if "timeout" in flags or st == "timeout":
        score = min(score, 0.42)

    level = "high"
    if score < float(os.getenv("CRAWL_QUALITY_MEDIUM_MAX", "0.55")):
        level = "medium"
    if score < float(os.getenv("CRAWL_QUALITY_LOW_MAX", "0.35")):
        level = "low"

    return {
        "crawl_quality_score": round(score, 4),
        "quality_level": level,
        "reliability_flags": flags,
        "explain": explain,
    }
