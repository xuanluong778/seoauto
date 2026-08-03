"""
TF-IDF (1–2 grams) + Agglomerative clustering for keyword grouping.
"""

from __future__ import annotations

from statistics import mean
from typing import Any

from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import TfidfVectorizer

from app.services.keyword_intent_rules import classify_intent_rules, majority_intent
from app.services.keyword_normalizer import normalize_keyword


def _cluster_name(keywords: list[str]) -> str:
    if not keywords:
        return ""
    return max(keywords, key=len)


def cluster_keywords_tfidf(
    rows: list[dict[str, Any]],
    *,
    distance_threshold: float = 0.5,
) -> list[dict[str, Any]]:
    """
    ``rows``: dicts with ``keyword``, ``search_volume`` (``avg_monthly``), ``cpc_avg``, optional ``intent``.

    Returns clusters with cluster_name, intent, keywords, total_volume, avg_cpc.
    """
    if not rows:
        return []
    pairs: list[tuple[dict[str, Any], str]] = []
    for r in rows:
        k = str(r.get("keyword") or "").strip()
        if k:
            pairs.append((r, k))
    if not pairs:
        return []
    rows = [p[0] for p in pairs]
    kws = [p[1] for p in pairs]

    if len(kws) == 1:
        r0 = rows[0]
        vol = int((r0.get("search_volume") or {}).get("avg_monthly") or 0)
        cpc = float(r0.get("cpc_avg") or 0)
        intent = str(r0.get("intent") or classify_intent_rules(kws[0]))
        return [
            {
                "cluster_name": kws[0],
                "intent": intent,
                "keywords": kws,
                "total_volume": vol,
                "avg_cpc": round(cpc, 4),
            }
        ]

    texts = []
    for k in kws:
        n = normalize_keyword(k, remove_stopwords=True, stem=True)
        texts.append(n if n else k.lower())

    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),
        min_df=1,
        max_df=0.98,
        sublinear_tf=True,
        norm="l2",
    )
    try:
        X = vectorizer.fit_transform(texts)
    except ValueError:
        return _fallback_singletons(rows)

    Xd = X.toarray()

    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=distance_threshold,
        metric="cosine",
        linkage="average",
    )
    try:
        labels = clustering.fit_predict(Xd)
    except Exception:
        return _fallback_singletons(rows)

    buckets: dict[int, list[int]] = {}
    for i, lab in enumerate(labels):
        buckets.setdefault(int(lab), []).append(i)

    out: list[dict[str, Any]] = []
    for _lid, idxs in sorted(buckets.items(), key=lambda x: x[0]):
        members = [kws[i] for i in idxs]
        sub = [rows[i] for i in idxs]
        intents = [str(r.get("intent") or classify_intent_rules(str(r.get("keyword") or ""))) for r in sub]
        intent = majority_intent(intents)
        vols = [int((r.get("search_volume") or {}).get("avg_monthly") or 0) for r in sub]
        cpcs = [float(r.get("cpc_avg") or 0) for r in sub]
        out.append(
            {
                "cluster_name": _cluster_name(members),
                "intent": intent,
                "keywords": members,
                "total_volume": int(sum(vols)),
                "avg_cpc": round(float(mean(cpcs)) if cpcs else 0.0, 4),
            }
        )
    return out


def _fallback_singletons(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        kw = str(r.get("keyword") or "").strip()
        if not kw:
            continue
        vol = int((r.get("search_volume") or {}).get("avg_monthly") or 0)
        cpc = float(r.get("cpc_avg") or 0)
        intent = str(r.get("intent") or classify_intent_rules(kw))
        out.append(
            {
                "cluster_name": kw,
                "intent": intent,
                "keywords": [kw],
                "total_volume": vol,
                "avg_cpc": round(cpc, 4),
            }
        )
    return out
