"""
Hybrid keyword clustering: union–find trên điểm

    hybrid = core * intent_gate

với ``core`` = tổng có trọng số (semantic, SERP overlap | lexical TF–IDF),
``intent_gate`` = phạt mạnh khi ``intent_similarity`` thấp.

SERP overlap = ``SERP_SIM_URL_WEIGHT`` * Jaccard(URL) + (1 - w) * overlap chuẩn hóa theo domain
(sublinear theo số URL cùng domain, tránh bias domain lớn).

Ngưỡng nối cạnh được tinh chỉnh động theo ``log(keyword_count)`` (xem env
``HYBRID_CLUSTER_THRESHOLD_*``). Fallback khi không có SERP: semantic + lexical + cùng intent_gate.

SERP URLs được lọc ads/feature trong :mod:`app.services.serp_fetcher` trước overlap.

GSC: field ``url`` (source ``gsc``), ``gsc_page``, ``gsc_primary_url`` / ``gsc_landing_urls``
hoặc kết quả :func:`app.services.keyword_normalizer.merge_similar_keyword_records` —
khi **cả hai** keyword có landing, ``HYBRID_WEIGHT_GSC_URL`` tham gia ``core``.

Sau union–find: tách cluster theo intent nếu đa số < ``CLUSTER_INTENT_DOMINANCE_MIN``.
Tắt gộp keyword tương tự: ``KEYWORD_CLUSTER_MERGE_SIMILAR=0``.
"""

from __future__ import annotations

import math
import os
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import re
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import normalize as _sp_normalize
from concurrent.futures import ProcessPoolExecutor

from app.services.search_intent import aggregate_cluster_intent, classify_search_intent, intent_similarity
from app.services.search_volume import enrich_keyword_volume, enrich_keyword_volumes_cached
from app.services import semantic_embedding as semantic_embedding_mod
from app.services.semantic_embedding import embed_keywords
from app.services.semantic_similarity import compute_semantic_similarity_matrix
from app.services.keyword_normalizer import merge_similar_keyword_records
from app.services.serp_fetcher import fetch_serp_for_keyword, normalize_serp_url
from app.services.serp_layout_intent import infer_serp_layout_intent
from app.services.serp_similarity import compute_serp_similarity
from app.services.keyword_preprocess import preprocess_keyword


def _page_type_from_url_only(url: str) -> str:
    u = str(url or "").strip().lower()
    try:
        p = urlparse(u)
        path = (p.path or "").lower()
    except Exception:
        path = ""
    if any(k in path for k in ("/product", "/products", "/shop", "/cart", "/checkout", "/san-pham", "/mua-")):
        return "product"
    if any(k in path for k in ("/category", "/categories", "/collections", "/danh-muc", "/directory")):
        return "category"
    if any(k in path for k in ("/blog", "/post", "/article", "/news", "/tin-tuc", "/huong-dan")):
        return "blog"
    if any(k in path for k in ("/landing", "/lp/", "/campaign")):
        return "landing"
    if any(k in path for k in ("/login", "/signin", "/register", "/signup")):
        return "login"
    if path in ("", "/"):
        return "homepage"
    return "other"


def _dominant_overlap_url(snapshots: dict[str, dict[str, Any]], members: list[str]) -> str | None:
    """
    Most frequent URL across member SERP lists.
    Tie-breakers: better avg rank, then lexicographic URL.
    """
    freq: dict[str, int] = {}
    rank_sum: dict[str, int] = {}
    for kw in members:
        snap = snapshots.get(kw) or {}
        urls = list(snap.get("serp_urls") or [])[:10]
        # Per-keyword unique URL positions only
        seen_local: set[str] = set()
        for pos, raw in enumerate(urls, start=1):
            u = normalize_serp_url(str(raw or ""))
            if not u or u in seen_local:
                continue
            seen_local.add(u)
            freq[u] = freq.get(u, 0) + 1
            rank_sum[u] = rank_sum.get(u, 0) + pos
    if not freq:
        return None
    ranked = sorted(freq.keys(), key=lambda u: (-freq.get(u, 0), rank_sum.get(u, 10**9), u))
    return ranked[0] if ranked else None


def _intent_from_page_type(pt: str) -> str:
    p = str(pt or "").strip().lower()
    if p in ("product", "category", "directory"):
        return "ecommerce"
    if p in ("landing",):
        return "commercial"
    if p in ("blog", "article", "news", "docs", "forum", "video"):
        return "informational"
    if p in ("homepage", "login"):
        return "navigational"
    return "informational"


def _dominant_intent_from_cluster_serp(mem_rows: list[dict[str, Any]]) -> dict[str, Any]:
    c: Counter[str] = Counter()
    for r in mem_rows:
        sig = r.get("serp_layout_intent") if isinstance(r, dict) else None
        if not isinstance(sig, dict):
            continue
        pd = sig.get("page_type_distribution")
        if not isinstance(pd, dict):
            continue
        for pt, share in pd.items():
            try:
                w = float(share or 0.0)
            except Exception:
                w = 0.0
            if w <= 0:
                continue
            c[_intent_from_page_type(str(pt))] += w
    if not c:
        return {"intent": "informational", "confidence": 0.0, "distribution": {}}
    total = float(sum(c.values()) or 1.0)
    dist = {k: round(float(v) / total, 4) for k, v in c.items()}
    dom, dom_share = max(dist.items(), key=lambda kv: kv[1])
    return {"intent": str(dom), "confidence": round(float(dom_share), 4), "distribution": dist}


def _token_preview(text: str, max_features: int = 12) -> list[str]:
    import re

    try:
        vec = TfidfVectorizer(max_features=max_features, ngram_range=(1, 2), min_df=1)
        mat = vec.fit_transform([text])
        feats = vec.get_feature_names_out()
        scores = np.asarray(mat.sum(axis=0)).ravel()
        order = np.argsort(-scores)
        return [str(feats[i]) for i in order[:8] if scores[i] > 0]
    except Exception:
        return []


def _cluster_block_worker(args: dict[str, Any]) -> dict[str, Any]:
    """
    CPU-bound block clustering worker (picklable).
    Returns: { "groups": [[global_idx...], ...], "merges_debug": [...]}.
    """
    import os
    import numpy as np
    from collections import defaultdict
    from sklearn.feature_extraction.text import HashingVectorizer
    from sklearn.neighbors import NearestNeighbors
    from sklearn.preprocessing import normalize as _sp_normalize_local

    sub_idxs: list[int] = list(args["sub_idxs"])
    phrases: list[str] = list(args["phrases"])
    tok_sets: list[set[str]] = list(args["tok_sets"])
    intents: list[str] = list(args["intents"])

    thr: float = float(args["thr"])
    w_hash: float = float(args["w_hash"])
    w_tok: float = float(args["w_tok"])
    max_cluster: int = int(args["max_cluster"])
    centroid_margin: float = float(args["centroid_margin"])
    var_split_min: int = int(args["var_split_min"])
    var_std_max: float = float(args["var_std_max"])
    topk: int = int(args["topk"])
    debug_on: bool = bool(args["debug_on"])

    if len(sub_idxs) < 2:
        return {"groups": [[i] for i in sub_idxs], "merges_debug": []}

    # HashingVectorizer: fit-free, sparse, L2 norm => cosine = dot.
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

    def jacc(sa: set[str], sb: set[str]) -> float:
        if not sa or not sb:
            return 0.0
        inter = len(sa & sb)
        if inter <= 0:
            return 0.0
        return inter / float(len(sa | sb) or 1)

    k = min(len(sub_idxs), max(2, topk + 1))
    nn = NearestNeighbors(n_neighbors=k, metric="cosine", algorithm="brute")
    nn.fit(X)
    dists, nbrs = nn.kneighbors(X, return_distance=True)

    # Pruning: even with ts=1, must be able to reach thr.
    min_hs = max(0.0, (thr - w_tok) / max(1e-9, w_hash))

    cand: list[tuple[int, int, float, float, float]] = []
    for a in range(dists.shape[0]):
        ia = sub_idxs[a]
        for j in range(1, dists.shape[1]):
            b = int(nbrs[a, j])
            if a >= b:
                continue
            ib = sub_idxs[b]
            if intents[a] != intents[b]:
                continue
            hs = float(1.0 - float(dists[a, j]))
            if hs < min_hs:
                continue
            ts = jacc(tok_sets[a], tok_sets[b])
            sc = w_hash * hs + w_tok * ts
            if sc >= thr:
                cand.append((ia, ib, sc, hs, ts))

    if not cand:
        return {"groups": [[i] for i in sub_idxs], "merges_debug": []}

    scores = np.array([c[2] for c in cand], dtype=np.float32)
    if scores.size > 200000:
        scores = scores[np.random.choice(scores.size, 200000, replace=False)]
    p80 = float(np.quantile(scores, 0.80)) if scores.size else thr
    dyn_thr = max(thr, p80 - 0.02)

    cand.sort(key=lambda x: -x[2])

    # local DSU across global indices (use dict mapping for compact arrays)
    idx_to_pos = {gid: p for p, gid in enumerate(sub_idxs)}
    parent = list(range(len(sub_idxs)))
    size = [1] * len(sub_idxs)
    sum_vec = [X[p] for p in range(len(sub_idxs))]

    def find_pos(p: int) -> int:
        while parent[p] != p:
            parent[p] = parent[parent[p]]
            p = parent[p]
        return p

    def can_merge(pa: int, pb: int, sc: float) -> bool:
        if pa == pb:
            return False
        if sc < dyn_thr:
            return False
        if size[pa] + size[pb] > max_cluster:
            return False
        va = sum_vec[pa]
        vb = sum_vec[pb]
        vm = va + vb
        ca = _sp_normalize_local(va)
        cb = _sp_normalize_local(vb)
        cm = _sp_normalize_local(vm)
        sa = float((ca @ cm.T).toarray().ravel()[0])
        sb = float((cb @ cm.T).toarray().ravel()[0])
        return min(sa, sb) >= max(0.0, dyn_thr - centroid_margin)

    merges_debug: list[dict[str, Any]] = []

    for ia, ib, sc, hs, ts in cand:
        pa = find_pos(idx_to_pos[ia])
        pb = find_pos(idx_to_pos[ib])
        if pa == pb:
            continue
        if not can_merge(pa, pb, sc):
            continue
        if size[pa] < size[pb]:
            pa, pb = pb, pa
        parent[pb] = pa
        size[pa] += size[pb]
        sum_vec[pa] = sum_vec[pa] + sum_vec[pb]
        if debug_on and len(merges_debug) < 120:
            merges_debug.append(
                {
                    "a": int(ia),
                    "b": int(ib),
                    "score": round(float(sc), 4),
                    "hash": round(float(hs), 4),
                    "tok": round(float(ts), 4),
                    "thr": round(float(dyn_thr), 4),
                }
            )

    comps: dict[int, list[int]] = defaultdict(list)
    for gid in sub_idxs:
        p = find_pos(idx_to_pos[gid])
        comps[p].append(gid)
    groups = list(comps.values())

    # Variance split within block
    new_groups: list[list[int]] = []
    for idxs in groups:
        if len(idxs) < max(3, var_split_min):
            new_groups.append(idxs)
            continue
        sample = idxs if len(idxs) <= 60 else idxs[:60]
        Xs = X[[idx_to_pos[g] for g in sample]]
        c_raw = np.asarray(X[[idx_to_pos[g] for g in idxs]].sum(axis=0))
        c = _sp_normalize_local(c_raw)
        sims = np.asarray(Xs @ c.T).ravel()
        if float(np.std(sims)) <= var_std_max:
            new_groups.append(idxs)
            continue
        order_s = np.argsort(sims)
        seed_lo = sample[int(order_s[0])]
        seed_hi = sample[int(order_s[-1])]
        c1 = _sp_normalize_local(X[idx_to_pos[seed_lo]])
        c2 = _sp_normalize_local(X[idx_to_pos[seed_hi]])
        g1: list[int] = []
        g2: list[int] = []
        for g in idxs:
            v = _sp_normalize_local(X[idx_to_pos[g]])
            s1 = float((v @ c1.T).toarray().ravel()[0])
            s2 = float((v @ c2.T).toarray().ravel()[0])
            (g1 if s1 >= s2 else g2).append(g)
        if len(g1) >= 2 and len(g2) >= 2:
            new_groups.append(g1)
            new_groups.append(g2)
        else:
            new_groups.append(idxs)
    return {"groups": new_groups, "merges_debug": merges_debug}


def _tfidf_cosine_matrix(phrases: list[str]) -> np.ndarray:
    max_feat = int(os.getenv("KEYWORD_CLUSTER_MAX_FEATURES", "4096"))
    vec = TfidfVectorizer(
        max_features=max_feat,
        ngram_range=(1, 2),
        min_df=1,
        sublinear_tf=True,
    )
    X = vec.fit_transform(phrases)
    return cosine_similarity(X).astype(np.float32)


def _tfidf_sparse_matrix(phrases: list[str]):
    max_feat = int(os.getenv("KEYWORD_CLUSTER_MAX_FEATURES", "4096"))
    vec = TfidfVectorizer(
        max_features=max_feat,
        ngram_range=(1, 2),
        min_df=1,
        sublinear_tf=True,
    )
    return vec.fit_transform(phrases)


def _hash_sparse_matrix(phrases: list[str]):
    """
    Fast, fit-free sparse vectorization for scalable clustering.

    HashingVectorizer avoids building a vocabulary (much faster for 2k–10k keywords).
    Output is L2-normalized so cosine similarity = dot product.
    """
    dim = int(os.getenv("KEYWORD_CLUSTER_HASH_DIM", "262144"))
    dim = max(16384, min(1048576, dim))
    hv = HashingVectorizer(
        n_features=dim,
        ngram_range=(1, 2),
        alternate_sign=False,
        norm="l2",
        lowercase=True,
    )
    return hv.transform(phrases)


def _union_find_from_edges(n: int, edges: list[tuple[int, int]]) -> list[list[int]]:
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


def _scalable_neighbor_edges(
    phrases: list[str],
    *,
    intent_labels: list[str],
    thr: float,
    gate_floor: float | None,
    k_neighbors: int,
) -> list[tuple[int, int]]:
    """
    Build union edges using blocking + TF-IDF cosine **within blocks**.

    This avoids full NxN comparisons and works better for 2k–10k keywords.
    """
    n = len(phrases)
    if n <= 1:
        return []

    # One global hashed sparse matrix (L2-normalized) so cosine similarity = dot product.
    X_all = _hash_sparse_matrix(phrases)

    stop = {
        "quan",
        "q",
        "huyen",
        "tphcm",
        "tp",
        "hcm",
        "hn",
        "ha",
        "noi",
        "ho",
        "chi",
        "minh",
        "tai",
        "gan",
        "gia",
        "re",
        "uy",
        "tin",
        "o",
        "tại",
        "gần",
        "giá",
        "rẻ",
        "uy",
        "tín",
    }

    def block_key(s: str, *, take: int) -> str:
        toks = [t for t in re.findall(r"[0-9a-zA-ZÀ-ỹ]+", (s or "").lower()) if len(t) > 1]
        toks = [t for t in toks if t not in stop]
        if not toks:
            toks = [t for t in re.findall(r"[0-9a-zA-ZÀ-ỹ]+", (s or "").lower()) if t]
        return " ".join(toks[:take]) if toks else (s or "").strip().lower()[:18]

    # Two-level blocking: key2 then (if still too big) key3.
    blocks: dict[str, list[int]] = defaultdict(list)
    for i, kw in enumerate(phrases):
        blocks[block_key(kw, take=2)].append(i)

    block_max = int(os.getenv("KEYWORD_CLUSTER_BLOCK_MAX", "420"))
    block_max = max(60, min(1200, block_max))

    # Build a list of sub-blocks to process
    sub_tasks: list[list[int]] = []
    for idxs in blocks.values():
        if len(idxs) < 2:
            continue
        if len(idxs) > block_max:
            sub: dict[str, list[int]] = defaultdict(list)
            for i in idxs:
                sub[block_key(phrases[i], take=3)].append(i)
            for v in sub.values():
                if len(v) >= 2:
                    sub_tasks.append(v)
        else:
            sub_tasks.append(idxs)

    hard_cap = int(os.getenv("KEYWORD_CLUSTER_BLOCK_HARD_CAP", "520"))
    hard_cap = max(120, min(1200, hard_cap))

    strict_intent = os.getenv("KEYWORD_CLUSTER_INTENT_STRICT", "1").lower() in ("1", "true", "yes")

    def edges_for_block(sub_idxs: list[int]) -> list[tuple[int, int]]:
        m = len(sub_idxs)
        if m < 2:
            return []
        if m > hard_cap:
            sub_idxs = sub_idxs[:hard_cap]
            m = len(sub_idxs)
            if m < 2:
                return []
        Xb = X_all[sub_idxs]
        # Sparse cosine sim = dot product; keep sparse to avoid dense O(m^2) memory.
        S = (Xb @ Xb.T).tocoo()
        out: list[tuple[int, int]] = []
        for a, b, v in zip(S.row, S.col, S.data):
            if a >= b:
                continue
            ia = sub_idxs[int(a)]
            ib = sub_idxs[int(b)]
            if strict_intent and intent_labels[ia] != intent_labels[ib]:
                continue
            it = float(intent_similarity(intent_labels[ia], intent_labels[ib]))
            gate = _intent_match_gate(it, floor=gate_floor)
            if (float(v) * gate) >= thr:
                out.append((ia, ib))
        return out

    workers = int(os.getenv("KEYWORD_CLUSTER_BLOCK_WORKERS", "0"))
    if workers <= 0:
        try:
            import multiprocessing

            workers = max(1, min(12, int(multiprocessing.cpu_count() or 4)))
        except Exception:
            workers = 6

    edges: list[tuple[int, int]] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(edges_for_block, b) for b in sub_tasks]
        for fut in as_completed(futs):
            edges.extend(fut.result() or [])
    return edges


def _dynamic_cluster_threshold(base: float, n: int) -> float:
    """
    Điều chỉnh ngưỡng union–find theo cỡ tập keyword: n lớn hơn → thường nới/tight hơn một chút
    theo log để tránh nối chuỗi quá rộng hoặc quá tách rời.

    Hệ số qua env: ``HYBRID_CLUSTER_THRESHOLD_LOGN_COEF``, ``HYBRID_CLUSTER_THRESHOLD_N0``,
    ``HYBRID_CLUSTER_THRESHOLD_FLOOR``, ``HYBRID_CLUSTER_THRESHOLD_CAP``.
    """
    if n <= 1:
        return base
    coef = float(os.getenv("HYBRID_CLUSTER_THRESHOLD_LOGN_COEF", "0.034"))
    n0 = float(os.getenv("HYBRID_CLUSTER_THRESHOLD_N0", "10"))
    lo = float(os.getenv("HYBRID_CLUSTER_THRESHOLD_FLOOR", "0.38"))
    hi = float(os.getenv("HYBRID_CLUSTER_THRESHOLD_CAP", "0.70"))
    adj = base + coef * (math.log(max(n, 2)) - math.log(max(n0, 2)))
    return max(lo, min(hi, adj))


def _strictness_params(name: str | None) -> tuple[float, float | None, float | None]:
    """``(threshold_delta, intent_gate_floor_or_none, dominance_min_or_none)`` — None = dùng env mặc định."""
    n = (name or "normal").lower().strip()
    if n == "strict":
        return (0.052, 0.22, 0.82)
    if n == "loose":
        return (-0.045, 0.09, 0.62)
    return (0.0, None, None)


def _intent_match_gate(intent_sim: float, *, floor: float | None = None) -> float:
    """Nhân vào core similarity: intent khác → giá trị gần ``floor`` (phạt mạnh)."""
    f = float(os.getenv("HYBRID_INTENT_GATE_FLOOR", "0.14")) if floor is None else float(floor)
    power = float(os.getenv("HYBRID_INTENT_GATE_POWER", "1.15"))
    f = max(0.0, min(0.95, f))
    x = max(0.0, min(1.0, float(intent_sim)))
    return f + (1.0 - f) * (x**power)


def _pairwise_mean(mat: np.ndarray, idxs: list[int]) -> float:
    if len(idxs) < 2:
        return 1.0
    vals = []
    for a in range(len(idxs)):
        for b in range(a + 1, len(idxs)):
            vals.append(float(mat[idxs[a], idxs[b]]))
    return sum(vals) / len(vals) if vals else 0.0


def _dominant_serp_urls(snapshots: dict[str, dict[str, Any]], members: list[str], *, top: int = 8) -> list[str]:
    cnt: Counter[str] = Counter()
    for m in members:
        for u in snapshots.get(m, {}).get("serp_urls") or []:
            cnt[u] += 1
    return [u for u, _ in cnt.most_common(top)]


def _row_gsc_primary(row: dict[str, Any]) -> str | None:
    u = row.get("gsc_primary_url") or row.get("gsc_page")
    if u:
        try:
            return normalize_serp_url(str(u).strip())
        except Exception:
            return str(u).strip().lower()
    if str(row.get("source") or "") == "gsc" and row.get("url"):
        try:
            return normalize_serp_url(str(row.get("url")).strip())
        except Exception:
            return str(row.get("url")).strip().lower()
    lu = row.get("gsc_landing_urls")
    if isinstance(lu, list) and lu:
        try:
            return normalize_serp_url(str(lu[0]).strip())
        except Exception:
            return str(lu[0]).strip().lower()
    return None


def _pair_gsc_landing_similarity(ua: str | None, ub: str | None) -> float | None:
    """Chỉ khi cả hai keyword đều có landing GSC — dùng để ưu tiên cùng cluster."""
    if not ua or not ub:
        return None
    mis = float(os.getenv("HYBRID_GSC_URL_MISMATCH_SCORE", "0.1"))
    return 1.0 if ua == ub else mis


def _split_groups_by_intent_homogeneity(
    groups: list[list[int]],
    *,
    intent_labels: list[str],
    min_dom: float | None = None,
) -> list[list[int]]:
    """Tách cluster nếu intent chiếm đa số < ngưỡng (env hoặc ``min_dom``)."""
    thr = float(os.getenv("CLUSTER_INTENT_DOMINANCE_MIN", "0.72")) if min_dom is None else float(min_dom)
    out: list[list[int]] = []
    for idxs in groups:
        if len(idxs) <= 1:
            out.append(idxs)
            continue
        labs = [intent_labels[i] for i in idxs]
        ct = Counter(labs)
        dom, c = ct.most_common(1)[0]
        if c / len(idxs) >= thr:
            out.append(idxs)
            continue
        main = [i for i in idxs if intent_labels[i] == dom]
        if main:
            out.append(main)
        rest = [i for i in idxs if intent_labels[i] != dom]
        buckets: dict[str, list[int]] = defaultdict(list)
        for i in rest:
            buckets[intent_labels[i]].append(i)
        for buck in buckets.values():
            if buck:
                out.append(buck)
    return out


def _split_groups_to_single_intent(
    groups: list[list[int]],
    *,
    intent_labels: list[str],
) -> list[list[int]]:
    """
    Hard split: each output group contains exactly one intent label.
    """
    out: list[list[int]] = []
    for idxs in groups:
        if len(idxs) <= 1:
            out.append(idxs)
            continue
        buckets: dict[str, list[int]] = defaultdict(list)
        for i in idxs:
            buckets[str(intent_labels[i] or "informational")].append(i)
        for b in buckets.values():
            if b:
                out.append(b)
    return out


def _kw_token_set(kw: str) -> set[str]:
    toks = [t.strip().lower() for t in str(kw or "").split() if t and t.strip()]
    return {t for t in toks if len(t) >= 2}


def _kw_overlap_ratio(a: str, b: str) -> float:
    sa = _kw_token_set(a)
    sb = _kw_token_set(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    if inter <= 0:
        return 0.0
    union = len(sa | sb)
    return (inter / union) if union else 0.0


def _cluster_adjusted_volume(mem_rows: list[dict[str, Any]]) -> tuple[int, int]:
    """
    Return (raw_sum, adjusted_sum) with overlap-aware damping to avoid inflated volumes.
    """
    if not mem_rows:
        return 0, 0
    rows = [r for r in mem_rows if isinstance(r, dict)]
    raw = int(sum(int(r.get("search_volume") or 0) for r in rows))
    if not rows:
        return raw, raw

    # Higher-volume terms are considered primary; overlapping terms are damped.
    rows_sorted = sorted(rows, key=lambda r: -int(r.get("search_volume") or 0))
    alpha = max(0.0, min(1.0, float(os.getenv("KEYWORD_CLUSTER_VOLUME_OVERLAP_ALPHA", "0.65"))))
    min_weight = max(0.1, min(1.0, float(os.getenv("KEYWORD_CLUSTER_VOLUME_MIN_WEIGHT", "0.35"))))
    seen_kws: list[str] = []
    adjusted = 0.0
    for r in rows_sorted:
        kw = str(r.get("keyword") or "").strip()
        vol = float(int(r.get("search_volume") or 0))
        if not kw or vol <= 0:
            continue
        max_ov = 0.0
        for sk in seen_kws:
            ov = _kw_overlap_ratio(kw, sk)
            if ov > max_ov:
                max_ov = ov
        weight = 1.0 - alpha * max_ov
        if weight < min_weight:
            weight = min_weight
        adjusted += vol * weight
        seen_kws.append(kw)
    return raw, int(round(adjusted))


def _readable_cluster_label(primary: str, variations: list[str], *, max_len: int = 120) -> str:
    """
    Build a human-friendly cluster label:
    - primary keyword first
    - optional refinement from high-signal variations
    """
    p = str(primary or "").strip()
    vars_clean = [str(v or "").strip() for v in (variations or []) if str(v or "").strip()]
    if not p and vars_clean:
        p = vars_clean[0]
    if not p:
        return "Keyword cluster"

    base_tokens = _kw_token_set(p)
    refiners: list[str] = []
    seen_ref: set[str] = set()
    for v in vars_clean:
        if v.lower() == p.lower():
            continue
        vt = _kw_token_set(v)
        extra = [t for t in vt if t not in base_tokens]
        if not extra:
            continue
        # Keep short meaningful fragment from variation.
        frag = " ".join(v.split()[:4]).strip()
        if not frag:
            continue
        low = frag.lower()
        if low in seen_ref:
            continue
        seen_ref.add(low)
        refiners.append(frag)
        if len(refiners) >= 2:
            break

    if not refiners:
        return p[:max_len]
    label = f"{p} ({' / '.join(refiners)})"
    return label[:max_len]


def _content_type_from_intent(intent: str, dominant_url: str | None = None) -> str:
    it = str(intent or "").strip().lower()
    if it in ("ecommerce", "transactional"):
        return "product"
    if it in ("commercial", "navigational"):
        return "landing"
    # URL-level hint fallback
    pt = _page_type_from_url_only(dominant_url or "")
    if pt in ("product", "category"):
        return "product"
    if pt in ("landing", "homepage", "login"):
        return "landing"
    return "blog"


def _page_strategy_for_cluster(members: list[str], *, intent: str, serp_similarity_avg: float) -> str:
    """
    Decide whether to target one page or multiple pages.
    """
    uniq = len({str(m or "").strip().lower() for m in members if str(m or "").strip()})
    it = str(intent or "").strip().lower()
    if uniq <= 2:
        return "single_page"
    if serp_similarity_avg >= 0.56 and it in ("informational", "commercial", "navigational"):
        return "single_page"
    if it in ("ecommerce", "transactional") and uniq >= 4:
        return "multiple_pages"
    if uniq >= 6:
        return "multiple_pages"
    return "single_page"


def _cluster_cohesion_score(
    idxs: list[int],
    *,
    sem_full: np.ndarray,
    lex_mat: np.ndarray,
    serp_mat: np.ndarray,
    hybrid: np.ndarray,
    intent_labels: list[str],
    gsc_primary: list[str | None],
    has_serp: bool,
) -> float:
    """0–1: semantic/SERP hoặc lexical + đồng nhất intent + (nếu có) GSC landing trùng."""
    if len(idxs) < 2:
        return 1.0
    sem_avg = _pairwise_mean(sem_full, idxs)
    lex_avg = _pairwise_mean(lex_mat, idxs)
    serp_avg = _pairwise_mean(serp_mat, idxs) if has_serp else 0.0
    labs = [intent_labels[i] for i in idxs]
    ih = Counter(labs).most_common(1)[0][1] / len(labs) if labs else 1.0
    g_urls = [gsc_primary[i] for i in idxs if gsc_primary[i]]
    if g_urls:
        gsc_coh = Counter(g_urls).most_common(1)[0][1] / len(g_urls)
    else:
        gsc_coh = ih
    if has_serp:
        w_sem_c = float(os.getenv("CLUSTER_COH_SEM_WEIGHT", "0.34"))
        w_serp_c = float(os.getenv("CLUSTER_COH_SERP_WEIGHT", "0.28"))
        w_int_c = float(os.getenv("CLUSTER_COH_INTENT_WEIGHT", "0.22"))
        w_gsc_c = float(os.getenv("CLUSTER_COH_GSC_WEIGHT", "0.16"))
        return round(
            w_sem_c * sem_avg + w_serp_c * serp_avg + w_int_c * ih + w_gsc_c * gsc_coh,
            4,
        )
    w_sem_c = float(os.getenv("CLUSTER_COH_FALLBACK_SEM", "0.52"))
    w_lex_c = float(os.getenv("CLUSTER_COH_FALLBACK_LEX", "0.30"))
    w_int_c = float(os.getenv("CLUSTER_COH_FALLBACK_INTENT", "0.18"))
    return round(w_sem_c * sem_avg + w_lex_c * lex_avg + w_int_c * ih, 4)


def _validate_split_groups(
    groups: list[list[int]],
    *,
    serp_mat: np.ndarray,
    intent_labels: list[str],
    has_serp: bool,
) -> list[list[int]]:
    min_serp = float(os.getenv("HYBRID_CLUSTER_MIN_SERP_COHESION", "0.12"))
    max_second = float(os.getenv("HYBRID_CLUSTER_MAX_INTENT_SECOND", "0.38"))
    out: list[list[int]] = []
    for idxs in groups:
        if len(idxs) <= 1:
            out.append(idxs)
            continue
        intents = [intent_labels[i] for i in idxs]
        ct = Counter(intents)
        mc = ct.most_common(2)
        secondc = mc[1][1] if len(mc) > 1 else 0
        ratio_second = secondc / len(idxs)

        mean_serp = _pairwise_mean(serp_mat, idxs) if has_serp else 1.0

        if has_serp and mean_serp < min_serp:
            for i in idxs:
                out.append([i])
            continue
        if ratio_second >= max_second:
            buckets: dict[str, list[int]] = defaultdict(list)
            for i in idxs:
                buckets[intent_labels[i]].append(i)
            for _lab, bucket in buckets.items():
                if bucket:
                    out.append(bucket)
            continue
        out.append(idxs)
    return out


def _union_find_from_matrix(hybrid: np.ndarray, thr: float) -> list[list[int]]:
    n = hybrid.shape[0]
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

    for i in range(n):
        for j in range(i + 1, n):
            if hybrid[i, j] >= thr:
                union(i, j)
    comps: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        comps[find(i)].append(i)
    return list(comps.values())


def cluster_keywords(
    keyword_records: list[dict[str, Any]],
    *,
    similarity_threshold: float | None = None,
    brand_terms: set[str] | None = None,
    fetch_serp: bool | None = None,
    serp_country: str | None = None,
    serp_language: str | None = None,
    serp_device: str | None = None,
    cluster_strictness: str | None = None,
    progress_hook: callable | None = None,
) -> list[dict[str, Any]]:
    """
    Hybrid clustering with optional SERP fetch (see env ``SERP_FETCH_ENABLED``).

    ``cluster_strictness``: ``strict`` | ``normal`` | ``loose`` — điều chỉnh ngưỡng nối cạnh + intent gate + tách intent.
    """
    if not keyword_records:
        return []

    def _progress(pct: int, msg: str) -> None:
        try:
            if progress_hook:
                progress_hook(int(pct), str(msg))
        except Exception:
            return

    bench_fast = os.getenv("BENCH_FAST", "0").lower() in ("1", "true", "yes")
    debug_mode = os.getenv("KEYWORD_CLUSTER_DEBUG_MODE", "0").lower() in ("1", "true", "yes")

    rec_in: list[dict[str, Any]] = list(keyword_records)
    if (not bench_fast) and os.getenv("KEYWORD_CLUSTER_MERGE_SIMILAR", "1").lower() in ("1", "true", "yes"):
        rec_in = merge_similar_keyword_records(rec_in)

    phrases = list(dict.fromkeys(str(r.get("keyword") or "").strip() for r in rec_in if r.get("keyword")))
    phrases = [p for p in phrases if p]
    if not phrases:
        return []

    _progress(3, "Chuẩn hoá danh sách keyword")

    scalable_n_prefetch = int(os.getenv("KEYWORD_CLUSTER_SCALABLE_N", "1200"))
    vol_batch: dict[str, dict[str, Any]] = {}
    if (not bench_fast) and len(phrases) >= scalable_n_prefetch:
        try:
            rows = enrich_keyword_volumes_cached(list(phrases))
            for r in rows or []:
                k = str(r.get("keyword") or "").strip().lower()
                if k:
                    vol_batch[k] = r
        except Exception:
            vol_batch = {}

    thr_base = float(
        similarity_threshold
        if similarity_threshold is not None
        else os.getenv("HYBRID_CLUSTER_THRESHOLD", "0.52")
    )
    strict = (cluster_strictness or os.getenv("KEYWORD_CLUSTER_STRICTNESS", "normal") or "normal").lower().strip()
    thr_delta, gate_floor_ov, dom_min_ov = _strictness_params(strict)
    thr_base = max(0.26, min(0.86, thr_base + thr_delta))
    w_sem = float(os.getenv("HYBRID_WEIGHT_SEMANTIC", "0.5"))
    w_serp = float(os.getenv("HYBRID_WEIGHT_SERP", "0.4"))
    w_int = float(os.getenv("HYBRID_WEIGHT_INTENT", "0.1"))
    w_sem_f = float(os.getenv("HYBRID_FALLBACK_WEIGHT_SEMANTIC", "0.55"))
    w_lex_f = float(os.getenv("HYBRID_FALLBACK_WEIGHT_LEXICAL", "0.35"))
    w_int_f = float(os.getenv("HYBRID_FALLBACK_WEIGHT_INTENT", "0.1"))
    w_gsc = float(os.getenv("HYBRID_WEIGHT_GSC_URL", "0.14"))

    if fetch_serp is None:
        fetch_serp = os.getenv("SERP_FETCH_ENABLED", "0").lower() in ("1", "true", "yes")

    brand = brand_terms or set()
    enriched_kw: list[dict[str, Any]] = []
    for r in rec_in:
        kw = str(r.get("keyword") or "").strip()
        if not kw:
            continue
        low_kw = kw.lower()
        if bench_fast:
            vol = {"search_volume": 0, "volume_source": "bench", "confidence": 0.0}
        elif vol_batch:
            # When we already did a batch pass (large N), avoid per-keyword DB/API calls.
            # Missing rows fall back to heuristic immediately (fast + deterministic).
            vol = vol_batch.get(low_kw)
            if not vol:
                from app.services.search_volume import _heuristic_volume

                v, c = _heuristic_volume(kw)
                vol = {"search_volume": v, "volume_source": "estimated", "confidence": c}
        else:
            vol = enrich_keyword_volume(kw)
        pp = preprocess_keyword(kw)
        intent = classify_search_intent(kw, brand_terms=brand)
        enriched_kw.append(
            {
                **r,
                "search_volume": vol["search_volume"],
                "volume_source": vol["volume_source"],
                "volume_confidence": vol["confidence"],
                "intent": intent["intent"],
                "intent_confidence": intent["confidence"],
                "intent_reasoning": intent.get("reasoning"),
                "kw_norm": pp.get("norm") or "",
                "kw_tokens": pp.get("tokens") or [],
            }
        )
    kw_by_phrase = {str(r.get("keyword") or "").strip().lower(): r for r in enriched_kw}
    ordered = [p for p in phrases if p.lower() in kw_by_phrase]
    if not ordered:
        return []
    n = len(ordered)
    # SERP-overlap clustering (requested):
    # similarity = intersection(URLs) / union(URLs)  (Jaccard)
    # cluster if similarity > 0.5
    thr = float(os.getenv("KEYWORD_CLUSTER_SERP_JACCARD_THRESHOLD", "0.5"))
    thr = max(0.01, min(0.99, thr))
    url_fanout_cap = int(os.getenv("KEYWORD_CLUSTER_SERP_URL_FANOUT_CAP", "60"))
    url_fanout_cap = max(10, min(800, url_fanout_cap))

    scalable_on = False
    embeddings: dict[str, Any] = {}
    sem_full = None
    lex_mat = None

    snapshots: dict[str, dict[str, Any]] = {}
    if fetch_serp:
        _progress(18, f"Fetch SERP ({len(ordered)} keyword)…")
        top_n = int(os.getenv("SERP_TOP_N", "10"))
        # Concurrency helps a lot; default 8 threads.
        # Note: providers may rate-limit; tune SERP_FETCH_CONCURRENCY as needed.
        workers = int(os.getenv("SERP_FETCH_CONCURRENCY", "8"))
        workers = max(1, min(32, workers))

        def _fetch_one(q: str) -> tuple[str, dict[str, Any]]:
            return (
                q,
                fetch_serp_for_keyword(
                    q,
                    top_n=top_n,
                    country=serp_country,
                    language=serp_language,
                    device=serp_device,
                ),
            )

        done = 0
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_fetch_one, k) for k in ordered]
            for fut in as_completed(futs):
                k, snap = fut.result()
                snapshots[k] = snap
                done += 1
                pct = 18 + int(52 * (done / max(1, len(ordered))))
                _progress(pct, f"Fetch SERP {done}/{len(ordered)}")

    _progress(72, "Tính intent theo SERP/layout")
    for k in ordered:
        row = kw_by_phrase.get(k.lower())
        if row is None:
            continue
        if fetch_serp:
            sig = infer_serp_layout_intent(snapshots.get(k) or {})
            if sig:
                row["serp_layout_intent"] = sig
                # SERP-first intent: avoid keyword-rule dominance when SERP exists.
                pt_dist = sig.get("page_type_distribution") if isinstance(sig, dict) else {}
                if isinstance(pt_dist, dict) and pt_dist:
                    c: Counter[str] = Counter()
                    for pt, share in pt_dist.items():
                        try:
                            c[_intent_from_page_type(str(pt))] += float(share or 0.0)
                        except Exception:
                            continue
                    if c:
                        row["intent_cluster"] = str(c.most_common(1)[0][0])
                    else:
                        row["intent_cluster"] = "informational"
                else:
                    row["intent_cluster"] = "informational"
            else:
                row["intent_cluster"] = "informational"
        else:
            row["intent_cluster"] = str(row.get("intent") or "informational")

    has_serp = bool(fetch_serp) and any(len((snapshots.get(k) or {}).get("serp_urls") or []) > 0 for k in ordered)
    url_sets: list[set[str]] = []
    if has_serp:
        for k in ordered:
            snap = snapshots.get(k) or {}
            urls = list(snap.get("serp_urls") or [])[:10]
            url_sets.append({normalize_serp_url(u) for u in urls if str(u or "").strip()})
    else:
        url_sets = [set() for _ in ordered]

    intent_labels = [str(kw_by_phrase[ordered[i].lower()].get("intent_cluster") or "informational") for i in range(n)]

    gsc_primary: list[str | None] = [_row_gsc_primary(kw_by_phrase[k.lower()]) for k in ordered]

    _progress(84, "SERP overlap graph (Jaccard) + union-find")
    hybrid = None

    pair_inter: dict[tuple[int, int], int] = {}
    pair_sims: list[tuple[int, int, float]] = []
    inv: dict[str, list[int]] = defaultdict(list)
    if has_serp:
        for i, s in enumerate(url_sets):
            for u in s:
                inv[u].append(i)
        for u, idxs in inv.items():
            if len(idxs) < 2:
                continue
            if len(idxs) > url_fanout_cap:
                continue
            idxs.sort()
            for a_pos in range(len(idxs)):
                a = idxs[a_pos]
                for b_pos in range(a_pos + 1, len(idxs)):
                    b = idxs[b_pos]
                    key = (a, b)
                    pair_inter[key] = pair_inter.get(key, 0) + 1

        # exact Jaccard using intersection count + set sizes
        for (i, j), inter in pair_inter.items():
            sa = url_sets[i]
            sb = url_sets[j]
            if not sa or not sb:
                continue
            union = len(sa) + len(sb) - int(inter)
            if union <= 0:
                continue
            sim = float(inter) / float(union)
            pair_sims.append((i, j, sim))

    # Dynamic thresholding + over/under clustering correction loop.
    thr_base_eff = float(thr)
    dyn_info: dict[str, Any] = {"threshold_initial": round(thr_base_eff, 4)}
    if pair_sims:
        vals = sorted(s for _, _, s in pair_sims)
        try:
            p60 = vals[int(max(0, min(len(vals) - 1, round((len(vals) - 1) * 0.60))))]
            p80 = vals[int(max(0, min(len(vals) - 1, round((len(vals) - 1) * 0.80))))]
            # Bias threshold toward stronger links but keep near requested baseline.
            thr_dyn = 0.5 * thr_base_eff + 0.3 * p60 + 0.2 * p80
            thr_dyn = max(0.12, min(0.94, thr_dyn))
        except Exception:
            thr_dyn = thr_base_eff
    else:
        thr_dyn = thr_base_eff

    def _groups_for_threshold(thv: float) -> list[list[int]]:
        e = [(i, j) for i, j, s in pair_sims if s > thv]
        gs = _union_find_from_edges(n, e) if e else [[i] for i in range(n)]
        # soft split first, then hard intent split to guarantee one intent/cluster
        gs = _split_groups_by_intent_homogeneity(gs, intent_labels=intent_labels, min_dom=dom_min_ov)
        gs = _split_groups_to_single_intent(gs, intent_labels=intent_labels)
        return gs

    def _cluster_shape_metrics(gs: list[list[int]]) -> dict[str, float]:
        if not gs:
            return {"singleton_ratio": 1.0, "largest_ratio": 1.0, "avg_size": 1.0}
        sizes = [len(g) for g in gs if g]
        if not sizes:
            return {"singleton_ratio": 1.0, "largest_ratio": 1.0, "avg_size": 1.0}
        singleton_ratio = sum(1 for x in sizes if x <= 1) / float(len(sizes))
        largest_ratio = max(sizes) / float(max(1, n))
        avg_size = sum(sizes) / float(len(sizes))
        return {
            "singleton_ratio": float(singleton_ratio),
            "largest_ratio": float(largest_ratio),
            "avg_size": float(avg_size),
        }

    thr_eff = float(thr_dyn)
    groups = _groups_for_threshold(thr_eff)
    iter_log: list[dict[str, Any]] = []
    for _ in range(4):
        m = _cluster_shape_metrics(groups)
        over = (m["singleton_ratio"] >= 0.72) or (m["avg_size"] <= 1.45)
        under = (m["largest_ratio"] >= 0.44) or (len(groups) <= max(2, int(math.sqrt(max(1, n)) * 0.45)))
        iter_log.append(
            {
                "thr": round(thr_eff, 4),
                "clusters": int(len(groups)),
                "singleton_ratio": round(m["singleton_ratio"], 4),
                "largest_ratio": round(m["largest_ratio"], 4),
                "avg_size": round(m["avg_size"], 4),
                "over": bool(over),
                "under": bool(under),
            }
        )
        if over and not under:
            thr_eff = max(0.08, thr_eff - 0.04)
            groups = _groups_for_threshold(thr_eff)
            continue
        if under and not over:
            thr_eff = min(0.98, thr_eff + 0.04)
            groups = _groups_for_threshold(thr_eff)
            continue
        break
    dyn_info["threshold_dynamic"] = round(float(thr_dyn), 4)
    dyn_info["threshold_final"] = round(float(thr_eff), 4)
    dyn_info["iterations"] = iter_log

    _progress(92, "Tổng hợp cụm + gợi ý content type")
    strong_pairs: list[dict[str, Any]] = []
    # Surface top SERP pairs (by Jaccard) for explain/debug.
    if has_serp and pair_inter:
        tmp: list[dict[str, Any]] = []
        for (i, j), inter in pair_inter.items():
            sa = url_sets[i]
            sb = url_sets[j]
            if not sa or not sb:
                continue
            union = len(sa) + len(sb) - int(inter)
            if union <= 0:
                continue
            sim = float(inter) / float(union)
            if sim <= 0:
                continue
            tmp.append({"pair": f"{ordered[i]} | {ordered[j]}", "serp_jaccard": round(sim, 4)})
        tmp.sort(key=lambda x: -float(x.get("serp_jaccard") or 0.0))
        strong_pairs = tmp[:80]

    def _pair_in_cluster_members(pair: str, members: list[str]) -> bool:
        if "|" not in pair:
            return False
        a, _, b = [x.strip() for x in pair.partition("|")]
        ms = set(members)
        return a in ms and b in ms

    clusters: list[dict[str, Any]] = []
    for idxs in sorted(groups, key=lambda ix: -len(ix)):
        members = [ordered[i] for i in idxs]
        mem_rows = [kw_by_phrase[m.lower()] for m in members if m.lower() in kw_by_phrase]
        mem_rows.sort(key=lambda r: -int(r.get("search_volume") or 0))
        raw_total_vol, adjusted_total_vol = _cluster_adjusted_volume(mem_rows)
        total_vol = adjusted_total_vol
        agg_int = _dominant_intent_from_cluster_serp(mem_rows) if has_serp else aggregate_cluster_intent(mem_rows)
        dominant_url = _dominant_overlap_url(snapshots, members) if has_serp else None
        dominant_url_intent = _intent_from_page_type(_page_type_from_url_only(dominant_url or "")) if dominant_url else None
        if dominant_url_intent and has_serp:
            # Use dominant overlap URL as representative intent signal for the cluster.
            agg_int["intent"] = dominant_url_intent

        # SERP-only clustering: average Jaccard within the cluster (top10 URL sets).
        sem_avg = None
        hyb_avg = None
        vals: list[float] = []
        if has_serp and len(idxs) >= 2:
            for a in range(len(idxs)):
                ia = idxs[a]
                sa = url_sets[ia] if ia < len(url_sets) else set()
                for b in range(a + 1, len(idxs)):
                    ib = idxs[b]
                    sb = url_sets[ib] if ib < len(url_sets) else set()
                    if not sa or not sb:
                        continue
                    inter = len(sa & sb)
                    if inter <= 0:
                        continue
                    union = len(sa | sb)
                    if union <= 0:
                        continue
                    vals.append(float(inter) / float(union))
        serp_avg = (sum(vals) / len(vals)) if vals else (1.0 if len(idxs) <= 1 else 0.0)
        cohesion = round(float(serp_avg), 4)
        content_type = _content_type_from_intent(str(agg_int.get("intent") or ""), dominant_url)
        page_strategy = _page_strategy_for_cluster(members, intent=str(agg_int.get("intent") or ""), serp_similarity_avg=float(serp_avg))
        gsc_urls_in_cluster = [_row_gsc_primary(r) for r in mem_rows if _row_gsc_primary(r)]
        gsc_cohesion = None
        gsc_modal_url: str | None = None
        if gsc_urls_in_cluster:
            mc = Counter(str(u) for u in gsc_urls_in_cluster).most_common(1)[0]
            gsc_modal_url, top_c = mc[0], mc[1]
            gsc_cohesion = round(top_c / len(gsc_urls_in_cluster), 4)

        centroid_terms = _token_preview(" ".join(members))
        primary_kw = str((mem_rows[0].get("keyword") if mem_rows else members[0]) or members[0] or "").strip()
        name = _readable_cluster_label(primary_kw, members, max_len=120)
        if not name:
            name = (centroid_terms[0] if centroid_terms else members[0])[:120]

        dominant_urls = _dominant_serp_urls(snapshots, members) if has_serp else []

        # Debug payload is opt-in via KEYWORD_CLUSTER_DEBUG_MODE=1 only.
        if debug_mode:
            for r in mem_rows:
                k = str(r.get("keyword") or "")
                snap = snapshots.get(k) or {}
                r["debug"] = {
                    "serp_urls": (snap.get("serp_urls") or [])[:10],
                    "serp_source": snap.get("source"),
                    "embedding_cached": False,
                    "embedding_backend": "disabled_by_serp_overlap_clusterer",
                }

        clusters.append(
            {
                "cluster_id": "",
                "cluster_name": name,
                "keywords": mem_rows,
                "total_search_volume": int(total_vol),
                "intent": agg_int["intent"],
                "intent_confidence": agg_int["confidence"],
                "intent_distribution": agg_int.get("distribution"),
                "serp_intent_distribution_avg": agg_int.get("serp_intent_distribution_avg"),
                "dominant_url": dominant_url,
                "recommended_content_type": content_type,
                "recommended_page_strategy": page_strategy,
                "semantic_score_avg": None if sem_avg is None else round(sem_avg, 4),
                "serp_similarity_avg": round(serp_avg, 4),
                "hybrid_score_avg": None if hyb_avg is None else round(hyb_avg, 4),
                "cohesion_score": cohesion,
                "gsc_landing_cohesion": gsc_cohesion,
                "gsc_modal_landing_url": gsc_modal_url,
                "explain": {
                    "clustering_method": "serp_jaccard_union_find",
                    "threshold": thr_eff,
                    "threshold_base": thr_base,
                    "keyword_count": n,
                    "signals_used": ["serp_url_jaccard", "intent_post_split"],
                    "serp_url_fanout_cap": int(url_fanout_cap),
                    "dynamic_thresholding": dyn_info,
                    "intent_hard_split": True,
                    "cluster_intent_dominance_min": float(
                        dom_min_ov if dom_min_ov is not None else os.getenv("CLUSTER_INTENT_DOMINANCE_MIN", "0.72")
                    ),
                    "cluster_strictness": strict,
                    "cohesion_score": cohesion,
                    "gsc_validation": {
                        "landing_cohesion": gsc_cohesion,
                        "modal_landing_url": gsc_modal_url,
                        "keywords_with_gsc_url": len(gsc_urls_in_cluster),
                    },
                    "dominant_urls": dominant_urls,
                    "dominant_overlap_url": dominant_url,
                    "dominant_overlap_url_intent": dominant_url_intent,
                    "actionable_insights": {
                        "recommended_content_type": content_type,
                        "recommended_page_strategy": page_strategy,
                        "note": "single_page = one consolidated URL; multiple_pages = split by sub-intent/variation groups",
                    },
                    "centroid_terms": centroid_terms,
                    "strong_pairs": [p for p in strong_pairs if _pair_in_cluster_members(p["pair"], members)][:12],
                    "member_count": len(members),
                    "volume_raw_sum": int(raw_total_vol),
                    "volume_adjusted_sum": int(adjusted_total_vol),
                    "volume_overlap_alpha": float(os.getenv("KEYWORD_CLUSTER_VOLUME_OVERLAP_ALPHA", "0.65")),
                    "volume_min_weight": float(os.getenv("KEYWORD_CLUSTER_VOLUME_MIN_WEIGHT", "0.35")),
                    "serp_data_available": has_serp,
                    "serp_intent_distribution_avg": agg_int.get("serp_intent_distribution_avg"),
                    "serp_locale": {
                        "country": serp_country or os.getenv("SERP_DEFAULT_COUNTRY", "vn"),
                        "language": serp_language or os.getenv("SERP_DEFAULT_LANGUAGE", "vi"),
                        "device": serp_device or os.getenv("SERP_DEFAULT_DEVICE", "desktop"),
                    },
                    "debug_mode": bool(debug_mode),
                },
            }
        )

    clusters.sort(key=lambda x: -int(x.get("total_search_volume") or 0))
    for i, c in enumerate(clusters):
        c["cluster_id"] = f"c{i}"
        if debug_mode:
            kw_rows = c.get("keywords") or []
            for r in kw_rows:
                if isinstance(r, dict):
                    r["cluster_id"] = c["cluster_id"]
    _progress(100, "Hoàn tất")
    return clusters
