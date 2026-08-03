"""
SERP URL normalization, fanout filtering, and intent-gated overlap for keyword clustering.

Used by :mod:`app.services.keyword_clusterer` — does not replace union–find / Jaccard core.
"""

from __future__ import annotations

import logging
import os
from collections import Counter, defaultdict
from typing import Any

from app.services.search_intent import intent_merge_allowed, intent_similarity
from app.services.serp_fetcher import is_serp_noise_or_ad_url, normalize_serp_url

_LOG = logging.getLogger(__name__)


def intent_match_gate(intent_sim: float, *, floor: float | None = None) -> float:
    """Scale edge weight when intents diverge (same formula as hybrid clusterer)."""
    f = float(os.getenv("HYBRID_INTENT_GATE_FLOOR", "0.14")) if floor is None else float(floor)
    power = float(os.getenv("HYBRID_INTENT_GATE_POWER", "1.15"))
    f = max(0.0, min(0.95, f))
    x = max(0.0, min(1.0, float(intent_sim)))
    return f + (1.0 - f) * (x**power)


def filter_serp_url_for_overlap(raw: str) -> str | None:
    """Normalize + drop ads/noise URLs before Jaccard overlap."""
    u = normalize_serp_url(str(raw or "").strip())
    if not u or is_serp_noise_or_ad_url(u):
        return None
    return u


def build_url_sets_from_snapshots(
    snapshots: dict[str, dict[str, Any]],
    ordered: list[str],
    *,
    top_n: int = 10,
) -> list[set[str]]:
    out: list[set[str]] = []
    for k in ordered:
        snap = snapshots.get(k) or {}
        urls = list(snap.get("serp_urls") or [])[:top_n]
        s: set[str] = set()
        for raw in urls:
            u = filter_serp_url_for_overlap(raw)
            if u:
                s.add(u)
        out.append(s)
    return out


def jaccard_sets(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter <= 0:
        return 0.0
    union = len(a | b)
    return float(inter) / float(union) if union else 0.0


def build_all_pairwise_serp_overlaps(
    url_sets: list[set[str]],
) -> tuple[dict[tuple[int, int], int], list[dict[str, Any]]]:
    """Compare every keyword pair — required for reliable merge + debug."""
    n = len(url_sets)
    pair_inter: dict[tuple[int, int], int] = {}
    pair_details: list[dict[str, Any]] = []
    for i in range(n):
        si = url_sets[i] if i < len(url_sets) else set()
        for j in range(i + 1, n):
            sj = url_sets[j] if j < len(url_sets) else set()
            inter_set = si & sj
            inter = len(inter_set)
            key = (i, j)
            pair_inter[key] = inter
            pair_details.append(
                {
                    "i": i,
                    "j": j,
                    "shared_urls_count": inter,
                    "jaccard_score": round(jaccard_sets(si, sj), 4),
                    "shared_urls": sorted(inter_set)[:12],
                    "strength": classify_serp_pair_strength(inter),
                }
            )
    return pair_inter, pair_details


def build_serp_pair_intersections(
    url_sets: list[set[str]],
    *,
    fanout_cap: int,
) -> tuple[dict[tuple[int, int], int], dict[str, Any]]:
    """Full pairwise overlap (fanout_cap kept for stats compat; no URL skipped)."""
    pair_inter, pair_details = build_all_pairwise_serp_overlaps(url_sets)
    merge_pairs = sum(1 for v in pair_inter.values() if v >= serp_merge_min_shared_urls())
    weak_pairs = sum(1 for v in pair_inter.values() if 1 <= v < serp_merge_min_shared_urls())
    stats = {
        "inverted_urls": 0,
        "fanout_filtered_urls": 0,
        "pair_candidates": len(pair_inter),
        "pairwise_mode": "full",
        "merge_pair_count": merge_pairs,
        "weak_pair_count": weak_pairs,
        "pair_details_sample": pair_details[:120],
    }
    return pair_inter, stats


def pairwise_jaccard_from_intersections(
    pair_inter: dict[tuple[int, int], int],
    url_sets: list[set[str]],
) -> list[tuple[int, int, float]]:
    out: list[tuple[int, int, float]] = []
    for (i, j), inter in pair_inter.items():
        sa = url_sets[i]
        sb = url_sets[j]
        if not sa or not sb:
            continue
        union = len(sa) + len(sb) - int(inter)
        if union <= 0:
            continue
        out.append((i, j, float(inter) / float(union)))
    return out


def _strictness_params(strictness: str) -> dict[str, float]:
    s = (strictness or "normal").lower().strip()
    if s == "strict":
        return {
            "serp_delta": 0.06,
            "intent_override_min": 0.82,
            "intent_block_below": 0.55,
            "min_raw_serp": 0.52,
            "sem_weight": 0.10,
        }
    if s == "loose":
        return {
            "serp_delta": -0.05,
            "intent_override_min": 0.68,
            "intent_block_below": 0.38,
            "min_raw_serp": 0.34,
            "sem_weight": 0.08,
        }
    return {
        "serp_delta": 0.0,
        "intent_override_min": 0.76,
        "intent_block_below": 0.48,
        "min_raw_serp": 0.44,
        "sem_weight": 0.22,
    }


def apply_intent_gate_to_serp_pairs(
    raw_pairs: list[tuple[int, int, float]],
    *,
    intent_labels: list[str],
    strictness: str,
    gate_floor: float | None,
    semantic_lookup: dict[tuple[int, int], float] | None = None,
) -> tuple[list[tuple[int, int, float]], dict[str, Any]]:
    """
    Filter / re-weight SERP Jaccard pairs with intent gate.

    Returns ``(effective_pairs, meta)`` where effective score drives union–find threshold.
    """
    params = _strictness_params(strictness)
    override_min = float(
        os.getenv("KEYWORD_CLUSTER_SERP_INTENT_OVERRIDE", str(params["intent_override_min"]))
    )
    block_below = float(os.getenv("KEYWORD_CLUSTER_INTENT_BLOCK_SIM", str(params["intent_block_below"])))
    w_serp = float(os.getenv("HYBRID_WEIGHT_SERP", "0.55"))
    w_sem = float(os.getenv("HYBRID_WEIGHT_SEMANTIC", str(params["sem_weight"])))
    w_int = float(os.getenv("HYBRID_WEIGHT_INTENT", "0.10"))
    min_raw = max(0.08, params["min_raw_serp"] + params["serp_delta"])

    kept: list[tuple[int, int, float]] = []
    blocked_intent = 0
    weak_serp = 0

    for i, j, serp_sim in raw_pairs:
        ia = intent_labels[i]
        ib = intent_labels[j]

        if not intent_merge_allowed(ia, ib, serp_jaccard=serp_sim):
            blocked_intent += 1
            continue

        it = float(intent_similarity(ia, ib))

        gate = intent_match_gate(it, floor=gate_floor)

        if strictness == "strict":
            if serp_sim < min_raw:
                continue
            effective = serp_sim * gate
            if it < 0.72 and serp_sim < override_min:
                blocked_intent += 1
                continue
        elif strictness == "loose":
            sem = (semantic_lookup or {}).get((i, j), serp_sim * 0.7)
            effective = (0.78 * serp_sim + 0.12 * sem + 0.10 * it) * gate
            if serp_sim < 0.42:
                weak_serp += 1
        else:
            sem = (semantic_lookup or {}).get((i, j), serp_sim * 0.75)
            effective = (w_serp * serp_sim + w_sem * sem + w_int * it) * gate
            if it < block_below and serp_sim < override_min:
                blocked_intent += 1
                continue

        if effective <= 0:
            continue
        kept.append((i, j, effective))

    meta = {
        "blocked_by_intent": blocked_intent,
        "weak_serp_pairs": weak_serp,
        "pairs_in": len(raw_pairs),
        "pairs_kept": len(kept),
        "strictness": strictness,
        "intent_override_min": override_min,
    }
    if blocked_intent or weak_serp:
        _LOG.debug(
            "SERP intent gate: kept=%s blocked=%s weak_serp=%s strictness=%s",
            len(kept),
            blocked_intent,
            weak_serp,
            strictness,
        )
    return kept, meta


def build_semantic_lookup_for_pairs(
    phrases: list[str],
    pairs: list[tuple[int, int, float]],
) -> dict[tuple[int, int], float]:
    """Hash-vector cosine for pair list only (normal-mode hybrid balance)."""
    if not pairs or not phrases:
        return {}
    try:
        from sklearn.feature_extraction.text import HashingVectorizer

        dim = int(os.getenv("KEYWORD_CLUSTER_HASH_DIM", "262144"))
        dim = max(16384, min(1048576, dim))
        hv = HashingVectorizer(
            n_features=dim,
            ngram_range=(1, 2),
            alternate_sign=False,
            norm="l2",
            lowercase=True,
        )
        X = hv.transform(phrases)
        out: dict[tuple[int, int], float] = {}
        for i, j, _ in pairs:
            try:
                v = float((X[i] @ X[j].T).toarray()[0, 0])
            except Exception:
                v = 0.0
            out[(i, j)] = max(0.0, min(1.0, v))
        return out
    except Exception as exc:
        _LOG.debug("semantic lookup for SERP pairs failed: %s", exc)
        return {}


def split_over_clustered_groups(
    groups: list[list[int]],
    *,
    url_sets: list[set[str]],
    intent_labels: list[str],
    strictness: str,
) -> list[list[int]]:
    """Auto-split clusters with mixed intent or low SERP cohesion."""
    if not groups:
        return groups

    if strictness == "strict":
        min_cohesion, max_second = 0.28, 0.25
    elif strictness == "loose":
        min_cohesion, max_second = 0.12, 0.42
    else:
        min_cohesion, max_second = 0.18, 0.32

    out: list[list[int]] = []
    for idxs in groups:
        if len(idxs) <= 2:
            out.append(idxs)
            continue

        labs = [intent_labels[i] for i in idxs]
        ct = Counter(labs)
        second = ct.most_common(2)[1][1] if len(ct) > 1 else 0
        intent_second_ratio = second / len(idxs)

        coh_vals: list[float] = []
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                coh_vals.append(jaccard_sets(url_sets[idxs[a]], url_sets[idxs[b]]))
        mean_coh = sum(coh_vals) / len(coh_vals) if coh_vals else 1.0

        split = intent_second_ratio >= max_second or (
            mean_coh < min_cohesion and len(idxs) >= 3
        )
        if not split:
            out.append(idxs)
            continue

        buckets: dict[str, list[int]] = defaultdict(list)
        for i in idxs:
            buckets[intent_labels[i]].append(i)
        if len(buckets) > 1:
            for b in buckets.values():
                if b:
                    out.append(b)
            continue

        out.extend(_split_serp_outliers(idxs, url_sets))
    return out


def _split_serp_outliers(idxs: list[int], url_sets: list[set[str]]) -> list[list[int]]:
    """Remove low-connectivity keywords from an over-merged SERP cluster."""
    if len(idxs) <= 2:
        return [idxs]
    min_avg = float(os.getenv("KEYWORD_CLUSTER_OUTLIER_MIN_JACCARD", "0.10"))
    scored: list[tuple[float, int]] = []
    for i in idxs:
        others = [j for j in idxs if j != i]
        if not others:
            scored.append((1.0, i))
            continue
        avg = sum(jaccard_sets(url_sets[i], url_sets[j]) for j in others) / len(others)
        scored.append((avg, i))
    scored.sort()
    outliers = [i for avg, i in scored if avg < min_avg]
    core = [i for avg, i in scored if avg >= min_avg]
    if outliers and len(core) >= 2:
        parts: list[list[int]] = [core]
        for o in outliers:
            parts.append([o])
        return parts
    return [idxs]


def serp_merge_min_shared_urls() -> int:
    """Minimum shared top-10 URLs required to merge two keywords into one cluster."""
    return max(1, min(10, int(os.getenv("KEYWORD_CLUSTER_SERP_MIN_SHARED_URLS", "3"))))


def classify_serp_pair_strength(shared_count: int, *, min_merge: int | None = None) -> str:
    """Classify pair: ``merge`` (>=3 URLs), ``weak`` (1–2), ``none`` (0)."""
    m = min_merge if min_merge is not None else serp_merge_min_shared_urls()
    if shared_count >= m:
        return "merge"
    if shared_count >= 1:
        return "weak"
    return "none"


def union_find_from_edges(n: int, edges: list[tuple[int, int]]) -> list[list[int]]:
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for a, b in edges:
        if 0 <= a < n and 0 <= b < n and a != b:
            union(a, b)

    comps: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        comps[find(i)].append(i)
    return list(comps.values())


def build_serp_merge_edges(
    pair_inter: dict[tuple[int, int], int],
    *,
    min_merge: int | None = None,
) -> tuple[list[tuple[int, int]], list[dict[str, Any]]]:
    """Build union-find edges for pairs with >= min_merge shared URLs; track weak pairs (1–2)."""
    m = min_merge if min_merge is not None else serp_merge_min_shared_urls()
    merge_edges: list[tuple[int, int]] = []
    weak: list[dict[str, Any]] = []
    for (i, j), inter in pair_inter.items():
        strength = classify_serp_pair_strength(int(inter), min_merge=m)
        row = {
            "i": int(i),
            "j": int(j),
            "shared_urls": int(inter),
            "shared_urls_count": int(inter),
            "strength": strength,
        }
        if strength == "merge":
            merge_edges.append((int(i), int(j)))
        elif strength == "weak":
            weak.append(row)
    return merge_edges, weak


def post_merge_orphan_groups_by_serp(
    groups: list[list[int]],
    url_sets: list[set[str]],
    *,
    min_merge: int | None = None,
) -> list[list[int]]:
    """
    Attach orphan keyword(s) to a cluster when they share >= min_merge URLs with any member.
    Prevents short head terms standing alone while long-tail variants form a cluster.
    """
    m = min_merge if min_merge is not None else serp_merge_min_shared_urls()
    merged = [list(g) for g in groups if g]
    if len(merged) <= 1:
        return merged

    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(merged):
            if len(merged) <= 1:
                break
            g = merged[i]
            if len(g) != 1:
                i += 1
                continue
            solo = g[0]
            best_j = -1
            best_shared = 0
            for j, other_g in enumerate(merged):
                if j == i:
                    continue
                for other in other_g:
                    shared = len(url_sets[solo] & url_sets[other])
                    if shared > best_shared:
                        best_shared = shared
                        best_j = j
            if best_j >= 0 and best_shared >= m:
                merged[best_j].append(solo)
                merged.pop(i)
                changed = True
                continue
            i += 1
    return merged


def cluster_by_serp_shared_urls(
    n: int,
    url_sets: list[set[str]],
    *,
    min_merge: int | None = None,
    fanout_cap: int = 60,
) -> tuple[list[list[int]], list[dict[str, Any]], dict[tuple[int, int], int], dict[str, Any]]:
    """
    Cluster by counting shared normalized URLs in top-10 SERP (primary signal).

    Merge when shared URL count >= ``min_merge`` (default 3). Pairs with 1–2 shared URLs are
  recorded as weak relations but not merged.
    """
    min_m = min_merge if min_merge is not None else serp_merge_min_shared_urls()
    pair_inter, overlap_stats = build_serp_pair_intersections(url_sets, fanout_cap=fanout_cap)
    merge_edges, weak_relations = build_serp_merge_edges(pair_inter, min_merge=min_m)
    groups = union_find_from_edges(n, merge_edges) if merge_edges else [[i] for i in range(n)]
    groups = post_merge_orphan_groups_by_serp(groups, url_sets, min_merge=min_m)
    meta: dict[str, Any] = {
        **overlap_stats,
        "merge_edges": len(merge_edges),
        "weak_relation_count": len(weak_relations),
        "min_shared_urls_for_merge": min_m,
        "clustering_method": "serp_shared_url_count",
    }
    return groups, weak_relations, pair_inter, meta


def format_weak_relations(weak_relations: list[dict[str, Any]], ordered: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for w in weak_relations:
        i, j = int(w["i"]), int(w["j"])
        out.append(
            {
                "keyword_a": ordered[i] if 0 <= i < len(ordered) else "",
                "keyword_b": ordered[j] if 0 <= j < len(ordered) else "",
                "shared_urls": int(w.get("shared_urls") or 0),
                "strength": "weak",
                "label": "liên quan yếu",
            }
        )
    return out


def _pair_key(i: int, j: int) -> tuple[int, int]:
    return (i, j) if i < j else (j, i)


def compute_cluster_shared_url_metrics(
    idxs: list[int],
    url_sets: list[set[str]],
    pair_inter: dict[tuple[int, int], int],
) -> dict[str, Any]:
    """Per-cluster SERP metrics: max shared URL count (UI) + avg Jaccard."""
    if len(idxs) <= 1:
        return {
            "shared_urls_count": 0,
            "shared_urls_count_min": 0,
            "shared_urls_count_max": 0,
            "serp_overlap_score": 1.0 if len(idxs) == 1 else 0.0,
        }
    shared_counts: list[int] = []
    jaccards: list[float] = []
    for a in range(len(idxs)):
        for b in range(a + 1, len(idxs)):
            ia, ib = idxs[a], idxs[b]
            key = _pair_key(ia, ib)
            inter = pair_inter.get(key)
            if inter is None:
                sa = url_sets[ia] if ia < len(url_sets) else set()
                sb = url_sets[ib] if ib < len(url_sets) else set()
                inter = len(sa & sb)
            shared_counts.append(int(inter))
            jaccards.append(jaccard_sets(url_sets[ia], url_sets[ib]))
    return {
        "shared_urls_count": max(shared_counts) if shared_counts else 0,
        "shared_urls_count_min": min(shared_counts) if shared_counts else 0,
        "shared_urls_count_max": max(shared_counts) if shared_counts else 0,
        "serp_overlap_score": round(sum(jaccards) / len(jaccards), 4) if jaccards else 0.0,
    }


def cluster_pair_merge_details_for_members(
    idxs: list[int],
    ordered: list[str],
    url_sets: list[set[str]],
    pair_inter: dict[tuple[int, int], int],
    *,
    min_merge: int | None = None,
) -> list[dict[str, Any]]:
    """Debug rows: which pairs in this cluster merged and which URLs overlapped."""
    m = min_merge if min_merge is not None else serp_merge_min_shared_urls()
    idx_set = set(idxs)
    out: list[dict[str, Any]] = []
    for (i, j), inter in pair_inter.items():
        if i not in idx_set or j not in idx_set:
            continue
        if int(inter) < 1:
            continue
        inter_set = url_sets[i] & url_sets[j]
        out.append(
            {
                "keyword_a": ordered[i] if i < len(ordered) else "",
                "keyword_b": ordered[j] if j < len(ordered) else "",
                "shared_urls_count": int(inter),
                "jaccard_score": round(jaccard_sets(url_sets[i], url_sets[j]), 4),
                "shared_urls": sorted(inter_set)[:8],
                "merged": int(inter) >= m,
            }
        )
    out.sort(key=lambda x: (-int(x.get("shared_urls_count") or 0), str(x.get("keyword_a") or "")))
    return out


def detect_merge_suggestions(
    groups: list[list[int]],
    *,
    ordered: list[str],
    url_sets: list[set[str]],
    intent_labels: list[str],
    main_keywords: list[str],
) -> list[dict[str, Any]]:
    """Hints for separate clusters that share >=3 URLs (weak merge candidates)."""
    min_shared = serp_merge_min_shared_urls()
    suggestions: list[dict[str, Any]] = []
    for a in range(len(groups)):
        for b in range(a + 1, len(groups)):
            ga, gb = groups[a], groups[b]
            if not ga or not gb:
                continue
            best_shared = 0
            best_j = 0.0
            for i in ga:
                for j in gb:
                    inter = len(url_sets[i] & url_sets[j])
                    best_shared = max(best_shared, inter)
                    best_j = max(best_j, jaccard_sets(url_sets[i], url_sets[j]))
            if best_shared < min_shared:
                continue
            mk_a = main_keywords[a] if a < len(main_keywords) else ordered[ga[0]]
            mk_b = main_keywords[b] if b < len(main_keywords) else ordered[gb[0]]
            suggestions.append(
                {
                    "cluster_indices": [a, b],
                    "main_keywords": [mk_a, mk_b],
                    "shared_urls": best_shared,
                    "max_serp_jaccard": round(best_j, 4),
                    "reason": "cross_cluster_high_serp_overlap",
                }
            )
    return suggestions


def select_main_keyword(
    mem_rows: list[dict[str, Any]],
    *,
    cluster_intent: str,
) -> str:
    """
    Pick main keyword by volume (real only), brevity, intent fit, clarity — not volume-only sort.
    """
    if not mem_rows:
        return ""

    real_sources = frozenset({"api", "dataforseo", "api_cache", "google_ads"})

    def _vol(row: dict[str, Any]) -> int:
        src = str(row.get("volume_source") or "").lower()
        if src not in real_sources:
            return 0
        try:
            return max(0, int(row.get("search_volume") or 0))
        except (TypeError, ValueError):
            return 0

    best_kw = ""
    best_score = -1.0
    max_vol = max(_vol(r) for r in mem_rows) or 1

    for r in mem_rows:
        kw = str(r.get("keyword") or "").strip()
        if not kw:
            continue
        vol = _vol(r)
        words = kw.split()
        wc = len(words)
        row_intent = str(r.get("intent_cluster") or r.get("intent") or "").lower()
        intent_fit = 1.0 if row_intent == (cluster_intent or "").lower() else 0.45
        if 2 <= wc <= 5:
            len_score = 1.0
        elif wc <= 7:
            len_score = 0.75
        else:
            len_score = 0.5
        vol_score = (vol / max_vol) if vol > 0 else 0.25
        clarity = min(1.0, len(set(w.lower() for w in words)) / max(1, wc))
        score = vol_score * 0.35 + len_score * 0.22 + intent_fit * 0.25 + clarity * 0.18
        if score > best_score:
            best_score = score
            best_kw = kw
    return best_kw or str(mem_rows[0].get("keyword") or "").strip()
