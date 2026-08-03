"""
Normalize and deduplicate topical entities (synonyms, reordering, modifier stripping).

Feeds Topic Graph v2 — does NOT treat raw strings as distinct Google entities.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from typing import Any

_MODIFIER_PREFIX = re.compile(
    r"^(best|top|cheap|free|ultimate|complete|easy|quick|simple|new|"
    r"how to|what is|what are|guide to|review of)\s+",
    re.I,
)
_MODIFIER_SUFFIX = re.compile(
    r"\s+(guide|tutorial|review|reviews|tips|list|checklist|examples?|explained|meaning)$",
    re.I,
)
_STOP_ENTITY = frozenset(
    "a an the and or for to of in on at by from as is was are be has have had it we you "
    "this that these those with into over under about page home more info".split()
)
_TOKEN = re.compile(r"[a-z0-9\u00c0-\u024f]{2,}", re.I)


def normalize_entity_phrase(raw: str) -> str:
    """Lowercase, strip leading/trailing modifiers, collapse whitespace."""
    s = (raw or "").strip().lower()
    s = _MODIFIER_PREFIX.sub("", s)
    s = _MODIFIER_SUFFIX.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    toks = [t for t in _TOKEN.findall(s) if t not in _STOP_ENTITY and len(t) > 1]
    return " ".join(toks)


def _token_bag(s: str) -> frozenset[str]:
    return frozenset(t for t in _TOKEN.findall((s or "").lower()) if t not in _STOP_ENTITY and len(t) > 1)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _sorted_key(phrase: str) -> tuple[str, ...]:
    toks = sorted(_token_bag(phrase))
    return tuple(toks)


def resolve_entity_groups(
    raw_phrases: list[str],
    *,
    cluster_keywords: list[str] | None = None,
    use_embeddings: bool | None = None,
) -> list[dict[str, Any]]:
    """
    Cluster ``raw_phrases`` + optional ``cluster_keywords`` into canonical entities.

    Returns list of ``{canonical_entity, variants, confidence}``.
    """
    if use_embeddings is None:
        use_embeddings = os.getenv("TOPICAL_ENTITY_EMBED", "0").lower() in ("1", "true", "yes")

    seen: set[str] = set()
    pool: list[str] = []
    for p in raw_phrases or []:
        t = (p or "").strip()
        if len(t) < 3 or t in seen:
            continue
        seen.add(t)
        pool.append(t)
    for k in cluster_keywords or []:
        t = (k or "").strip().lower()
        if len(t) > 2 and t not in seen:
            seen.add(t)
            pool.append(t)

    if not pool:
        return []

    # Normalize each phrase to a stem phrase
    normalized: list[tuple[str, str]] = []  # (canonical_candidate, original)
    for p in pool:
        n = normalize_entity_phrase(p)
        if len(n) < 3:
            n = p.lower().strip()
        normalized.append((n, p))

    # Union-find by token-sort equality + high Jaccard
    parent: list[int] = list(range(len(normalized)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    n = len(normalized)
    bags = [_token_bag(normalized[i][0]) for i in range(n)]
    sort_keys = [_sorted_key(normalized[i][0]) for i in range(n)]

    for i in range(n):
        for j in range(i + 1, n):
            if sort_keys[i] and sort_keys[i] == sort_keys[j]:
                union(i, j)
            elif _jaccard(bags[i], bags[j]) >= 0.78:
                union(i, j)

    emb_merge: set[tuple[int, int]] = set()
    if use_embeddings and n <= 80:
        try:
            import numpy as np

            from app.services.semantic_embedding import embed_keywords

            phrases = [normalized[i][0] for i in range(n) if len(normalized[i][0]) > 2]
            vecs = embed_keywords(phrases)
            keys = [normalized[i][0] for i in range(n)]
            for i in range(n):
                vi = vecs.get(keys[i])
                if vi is None:
                    continue
                for j in range(i + 1, n):
                    vj = vecs.get(keys[j])
                    if vj is None:
                        continue
                    if float(np.dot(vi, vj)) >= 0.84:
                        emb_merge.add((i, j))
        except Exception:
            pass

    for i, j in emb_merge:
        union(i, j)

    groups: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(normalized[i])

    out: list[dict[str, Any]] = []
    for _root, members in sorted(groups.items(), key=lambda x: -len(x[1])):
        originals = [m[1] for m in members]
        norms = [m[0] for m in members]
        # canonical: longest normalized after tie-break by frequency
        canon = max(norms, key=lambda s: (len(s), norms.count(s)))
        variants = sorted({o for o in originals if o.lower() != canon}, key=len)[:20]
        # confidence: agreement of token bags
        bags_g = [_token_bag(x) for x in norms]
        if len(bags_g) < 2:
            conf = 0.88
        else:
            base = sum(_jaccard(bags_g[0], b) for b in bags_g[1:]) / max(1, len(bags_g) - 1)
            conf = round(min(0.97, 0.55 + 0.42 * base), 3)
        out.append(
            {
                "canonical_entity": canon,
                "variants": variants[:16],
                "confidence": conf,
            }
        )

    out.sort(key=lambda x: -len(x.get("canonical_entity") or ""))
    return out[:48]


def raw_entities_from_graph(graph: dict[str, Any]) -> list[str]:
    phrases: list[str] = []
    for n in graph.get("nodes") or []:
        t = str(n.get("topic") or "").strip()
        if t:
            phrases.append(t)
    return phrases


def similarity_phrase_to_canonical(phrase: str, canonical: str) -> float:
    """Token Jaccard on normalized surfaces (0–1)."""
    return _jaccard(_token_bag(normalize_entity_phrase(phrase)), _token_bag(canonical))


def cluster_keywords_from_topics(urls: list[str], topics_by_url: dict[str, dict[str, Any]]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for u in urls:
        row = topics_by_url.get(u) or {}
        for k in row.get("keywords") or []:
            ks = str(k).strip().lower()
            if len(ks) > 2 and ks not in seen:
                seen.add(ks)
                out.append(ks)
        for s in row.get("secondary_topics") or []:
            ss = str(s).strip().lower()
            if len(ss) > 2 and ss not in seen:
                seen.add(ss)
                out.append(ss)
    return out[:200]
