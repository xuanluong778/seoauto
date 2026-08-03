"""
SERP overlap: URL + domain, có trọng số theo thứ hạng (top 3 mạnh hơn tail),
tránh bias domain chiếm nhiều slot.
"""

from __future__ import annotations

import math
import os
from collections import defaultdict
from typing import Any
from urllib.parse import urlparse


def _registrable_domain(netloc: str) -> str:
    h = (netloc or "").lower().strip(".")
    if h.startswith("www."):
        h = h[4:]
    if not h:
        return ""
    parts = h.split(".")
    if len(parts) < 2:
        return parts[0] if parts else ""
    if len(parts) >= 3 and parts[-2] in ("co", "com", "net", "org", "gov", "ac", "edu"):
        tld = parts[-1]
        if len(tld) <= 3 or tld in ("uk", "vn", "jp", "kr", "au", "nz", "br", "mx"):
            return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _domain_for_url(url: str) -> str:
    try:
        p = urlparse(url)
        return _registrable_domain(p.netloc or "")
    except Exception:
        return ""


def _position_weights(n: int) -> list[float]:
    """Trọng số theo vị trí organic; top 3 cao hơn (``SERP_SIM_TOP3_MULTIPLIER``), trung bình ≈ 1."""
    if n <= 0:
        return []
    top_mul = float(os.getenv("SERP_SIM_TOP3_MULTIPLIER", "1.72"))
    raw = [top_mul if i < min(3, n) else 1.0 for i in range(n)]
    s = sum(raw)
    if s <= 0:
        return [1.0] * n
    scale = n / s
    return [r * scale for r in raw]


def _weighted_url_masses(urls: list[str]) -> dict[str, float]:
    ws = _position_weights(len(urls))
    out: dict[str, float] = {}
    for i, raw in enumerate(urls):
        u = str(raw or "").strip()
        if not u:
            continue
        w = float(ws[i] if i < len(ws) else ws[-1])
        out[u] = max(out.get(u, 0.0), w)
    return out


def _url_masses_to_domain_totals(url_masses: dict[str, float]) -> dict[str, float]:
    dd: dict[str, float] = defaultdict(float)
    for u, w in url_masses.items():
        d = _domain_for_url(u)
        if d:
            dd[d] += float(w)
    return dict(dd)


def _weighted_minmax_overlap(ma: dict[str, float], mb: dict[str, float]) -> float:
    keys = set(ma) | set(mb)
    if not keys:
        return 0.0
    num = 0.0
    den = 0.0
    for k in keys:
        num += min(ma.get(k, 0.0), mb.get(k, 0.0))
        den += max(ma.get(k, 0.0), mb.get(k, 0.0))
    return (num / den) if den > 0 else 0.0


def _weighted_domain_overlap_sublinear(url_ma: dict[str, float], url_mb: dict[str, float]) -> float:
    """Domain overlap, khối lượng √ trên tổng trọng số URL theo domain."""
    da = _url_masses_to_domain_totals(url_ma)
    db = _url_masses_to_domain_totals(url_mb)
    all_d = set(da) | set(db)
    if not all_d:
        return 0.0
    num = 0.0
    den = 0.0
    for d in all_d:
        va = math.sqrt(float(da.get(d, 0.0)))
        vb = math.sqrt(float(db.get(d, 0.0)))
        num += min(va, vb)
        den += max(va, vb)
    return (num / den) if den > 0 else 0.0


def _url_jaccard(ua: set[str], ub: set[str]) -> float:
    if not ua or not ub:
        return 0.0
    inter = len(ua & ub)
    union = len(ua | ub)
    return (inter / union) if union else 0.0


def _domain_damped_minmax(urls_a: list[str], urls_b: list[str]) -> float:
    """Domain min–max không trọng số hạng (test / debug)."""
    ca: dict[str, float] = defaultdict(float)
    for u in urls_a:
        d = _domain_for_url(str(u))
        if d:
            ca[d] += 1.0
    cb: dict[str, float] = defaultdict(float)
    for u in urls_b:
        d = _domain_for_url(str(u))
        if d:
            cb[d] += 1.0
    if not ca and not cb:
        return 0.0
    all_d = set(ca) | set(cb)
    num = 0.0
    den = 0.0
    for d in all_d:
        va = math.sqrt(float(ca.get(d, 0.0)))
        vb = math.sqrt(float(cb.get(d, 0.0)))
        num += min(va, vb)
        den += max(va, vb)
    return (num / den) if den > 0 else 0.0


def compute_serp_similarity(
    serp_a: dict[str, Any],
    serp_b: dict[str, Any],
    *,
    url_weight: float | None = None,
) -> float:
    """
    ``url_weight`` * overlap URL (trọng số hạng) + (1 - w) * overlap domain (sublinear).

    Mặc định ``SERP_SIM_URL_WEIGHT`` (~0.38).
    """
    raw_a = list(serp_a.get("serp_urls") or [])
    raw_b = list(serp_b.get("serp_urls") or [])
    if not raw_a or not raw_b:
        return 0.0
    w_url = float(url_weight if url_weight is not None else os.getenv("SERP_SIM_URL_WEIGHT", "0.38"))
    w_url = max(0.0, min(1.0, w_url))
    wa = _weighted_url_masses(raw_a)
    wb = _weighted_url_masses(raw_b)
    url_score = _weighted_minmax_overlap(wa, wb)
    dom_score = _weighted_domain_overlap_sublinear(wa, wb)
    s = w_url * url_score + (1.0 - w_url) * dom_score
    return round(float(s), 4)


def serp_similarity_matrix(
    snapshots: dict[str, dict[str, Any]],
    ordered: list[str],
    *,
    url_weight: float | None = None,
) -> list[list[float]]:
    """Pairwise matrix aligned with ``ordered`` keywords (for debugging / validation)."""
    n = len(ordered)
    mat = [[0.0] * n for _ in range(n)]
    for i in range(n):
        mat[i][i] = 1.0
        sa = snapshots.get(ordered[i]) or {}
        for j in range(i + 1, n):
            sb = snapshots.get(ordered[j]) or {}
            s = compute_serp_similarity(sa, sb, url_weight=url_weight)
            mat[i][j] = s
            mat[j][i] = s
    return mat
