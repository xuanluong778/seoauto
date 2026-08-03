"""
Dense keyword embeddings: sentence-transformers, OpenAI, or L2-normalized TF-IDF fallback.

Vectors are L2-normalized for cosine similarity = dot product.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

import numpy as np

_LOG = logging.getLogger(__name__)

LAST_BACKEND = "unknown"

_CACHE: dict[str, np.ndarray] = {}
_CACHE_ORDER: list[str] = []
_MAX_MEM = int(os.getenv("EMBEDDING_CACHE_MAX_KEYS", "8000"))


def _redis():
    try:
        import redis

        return redis.Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"))
    except Exception:
        return None


def _cache_get(key: str) -> np.ndarray | None:
    r = _redis()
    if r:
        try:
            raw = r.get(f"emb:{key}")
            if raw:
                return np.frombuffer(raw, dtype=np.float32)
        except Exception:
            pass
    return _CACHE.get(key)


def _cache_set(key: str, vec: np.ndarray) -> None:
    r = _redis()
    v = np.asarray(vec, dtype=np.float32).flatten()
    if r:
        try:
            r.setex(f"emb:{key}", int(os.getenv("EMBEDDING_CACHE_TTL", "604800")), v.tobytes())
            return
        except Exception:
            pass
    if len(_CACHE_ORDER) >= _MAX_MEM and key not in _CACHE:
        old = _CACHE_ORDER.pop(0)
        _CACHE.pop(old, None)
    _CACHE[key] = v.copy()
    if key not in _CACHE_ORDER:
        _CACHE_ORDER.append(key)


def _kw_key(kw: str) -> str:
    return hashlib.sha256(kw.strip().lower().encode("utf-8")).hexdigest()


def _l2_normalize(mat: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(mat, axis=1, keepdims=True)
    n = np.maximum(n, 1e-12)
    return mat / n


def _embed_openai(keywords: list[str]) -> dict[str, np.ndarray] | None:
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        return None
    model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    try:
        import urllib.request

        out: dict[str, np.ndarray] = {}
        batch = int(os.getenv("OPENAI_EMBEDDING_BATCH", "64"))
        for i in range(0, len(keywords), batch):
            chunk = keywords[i : i + batch]
            body = json.dumps({"model": model, "input": chunk}).encode()
            req = urllib.request.Request(
                "https://api.openai.com/v1/embeddings",
                data=body,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
            items = sorted(data.get("data", []), key=lambda x: int(x.get("index", 0)))
            for pos, item in enumerate(items):
                if pos >= len(chunk):
                    break
                emb = np.array(item.get("embedding") or [], dtype=np.float32)
                v = _l2_normalize(emb.reshape(1, -1))[0]
                out[chunk[pos]] = v
        return out if len(out) == len(keywords) else None
    except Exception as exc:
        _LOG.debug("OpenAI embeddings failed: %s", exc)
        return None


def _embed_sentence_transformers(keywords: list[str]) -> dict[str, np.ndarray] | None:
    model_name = (os.getenv("SEMANTIC_EMBEDDING_MODEL") or "all-MiniLM-L6-v2").strip()
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(model_name)
        vecs = model.encode(
            keywords,
            batch_size=int(os.getenv("ST_EMBEDDING_BATCH", "32")),
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        out: dict[str, np.ndarray] = {}
        for i, k in enumerate(keywords):
            out[k] = np.asarray(vecs[i], dtype=np.float32).flatten()
        return out
    except Exception as exc:
        _LOG.debug("sentence-transformers not used: %s", exc)
        return None


def _embed_tfidf_dense(keywords: list[str]) -> dict[str, np.ndarray]:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import normalize

    max_f = min(int(os.getenv("KEYWORD_CLUSTER_MAX_FEATURES", "4096")), 8192)
    vec = TfidfVectorizer(max_features=max_f, ngram_range=(1, 2), min_df=1, sublinear_tf=True)
    X = vec.fit_transform(keywords)
    Xd = X.toarray().astype(np.float32)
    Xn = normalize(Xd, norm="l2", axis=1)
    return {k: Xn[i] for i, k in enumerate(keywords)}


def embed_keywords(keywords: list[str], *, use_cache: bool = True) -> dict[str, np.ndarray]:
    """
    Return mapping ``keyword ->`` L2-normalized dense ``np.ndarray`` (float32).

    Resolution order: per-keyword cache → sentence-transformers → OpenAI → TF-IDF.
    """
    uniq = list(dict.fromkeys(k.strip() for k in keywords if k and k.strip()))
    if not uniq:
        return {}

    out: dict[str, np.ndarray] = {}
    pending: list[str] = []
    for k in uniq:
        ck = _kw_key(k)
        if use_cache:
            hit = _cache_get(ck)
            if hit is not None and hit.size > 0:
                out[k] = hit
                continue
        pending.append(k)

    if not pending:
        return out

    global LAST_BACKEND

    emb = _embed_sentence_transformers(pending)
    if emb is not None:
        LAST_BACKEND = "sentence_transformers"
    if emb is None:
        emb = _embed_openai(pending)
        if emb is not None:
            LAST_BACKEND = "openai"
    if emb is None:
        emb = _embed_tfidf_dense(pending)
        LAST_BACKEND = "tfidf_dense"

    for k, v in emb.items():
        v = np.asarray(v, dtype=np.float32).flatten()
        nv = _l2_normalize(v.reshape(1, -1))[0]
        out[k] = nv
        if use_cache:
            _cache_set(_kw_key(k), nv)

    return out
