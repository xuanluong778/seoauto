"""WAVE 5 — embedding worker + WP corpus cache tests."""

from __future__ import annotations

import concurrent.futures

import numpy as np
import pytest

from app.services.content_ai_duplicate_detection import (
    MSG_SAME_INTENT,
    ExistingArticleRef,
    check_keywords_for_duplicates,
)
from app.services import embedding_cache
from app.services.duplicate_wp_corpus_cache import (
    get_live_site_articles_cached,
    invalidate_wp_corpus_for_site,
    metrics_snapshot as wp_metrics,
    patch_wp_corpus_post,
    ref_from_dict,
    ref_to_dict,
    reset_metrics as reset_wp_metrics,
)
from app.services.embedding_worker_rollout import (
    embedding_celery_enabled,
    is_embedding_worker_process,
    uvicorn_may_load_embedding_model,
)
from app.services.semantic_embedding import embed_keywords, embed_keywords_local


def _ref(keyword: str, **kwargs) -> ExistingArticleRef:
    title = kwargs.pop("title", keyword)
    return ExistingArticleRef(keyword=keyword, title=title, **kwargs)


def test_uvicorn_blocks_st_when_celery_embedding_enabled(monkeypatch):
    monkeypatch.setenv("EMBEDDING_CELERY_WORKER", "1")
    monkeypatch.delenv("CELERY_EMBEDDING_WORKER", raising=False)
    assert embedding_celery_enabled()
    assert not uvicorn_may_load_embedding_model()


def test_embedding_worker_may_load_model(monkeypatch):
    monkeypatch.setenv("EMBEDDING_CELERY_WORKER", "1")
    monkeypatch.setenv("CELERY_EMBEDDING_WORKER", "1")
    assert is_embedding_worker_process()


def test_tenant_scoped_embedding_cache_isolation(monkeypatch):
    monkeypatch.setenv("EMBEDDING_CACHE_VERSION", "99")
    embedding_cache.reset_metrics()
    vec = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    digest = embedding_cache.content_hash("sửa máy tính quận 9")
    embedding_cache.cache_set(tenant_scope="tenant-a", digest=digest, vec=vec, ttl=60)
    hit_a = embedding_cache.cache_get(tenant_scope="tenant-a", digest=digest)
    hit_b = embedding_cache.cache_get(tenant_scope="tenant-b", digest=digest)
    assert hit_a is not None
    assert hit_b is None


def test_embed_keywords_delegates_to_celery(monkeypatch):
    monkeypatch.setenv("EMBEDDING_CELERY_WORKER", "1")
    monkeypatch.delenv("CELERY_EMBEDDING_WORKER", raising=False)
    called: list[str] = []

    def _fake_worker(keywords, *, tenant_scope="global", timeout=None):
        called.append(tenant_scope)
        return {"kw": np.array([1.0, 0.0], dtype=np.float32)}

    monkeypatch.setattr(
        "app.workers.embedding_tasks.embed_keywords_via_worker",
        _fake_worker,
    )
    out = embed_keywords(["kw"], tenant_scope="42")
    assert "42" in called
    assert "kw" in out


def test_embed_keywords_local_uses_tenant_cache(monkeypatch):
    monkeypatch.setenv("EMBEDDING_CELERY_WORKER", "0")
    monkeypatch.setenv("CELERY_EMBEDDING_WORKER", "1")
    vec = np.array([0.6, 0.8], dtype=np.float32)
    vec = vec / np.linalg.norm(vec)

    def _fake_st(keywords):
        return {k: vec.copy() for k in keywords}

    monkeypatch.setattr(
        "app.services.semantic_embedding._embed_sentence_transformers",
        _fake_st,
    )
    embedding_cache.reset_metrics()
    embed_keywords_local(["alpha"], tenant_scope="u1", use_cache=True)
    embed_keywords_local(["alpha"], tenant_scope="u1", use_cache=True)
    assert embedding_cache.metrics_snapshot()["cache_hits"] >= 1


def test_wp_corpus_cache_hit_miss(monkeypatch):
    monkeypatch.setenv("DUPLICATE_WP_CORPUS_CACHE", "1")
    monkeypatch.setenv("DUPLICATE_WP_ASYNC_FETCH", "0")
    reset_wp_metrics()
    refs = [_ref("sửa máy tính quận 9", url="https://ex.test/a")]
    fetch_calls = {"n": 0}

    def _fake_live(**kwargs):
        fetch_calls["n"] += 1
        return refs

    monkeypatch.setattr(
        "app.services.content_ai_duplicate_detection._collect_live_site_articles",
        _fake_live,
    )
    monkeypatch.setattr(
        "app.services.duplicate_wp_corpus_cache._cache_get",
        lambda key: None,
    )
    stored: dict[str, list] = {}

    def _fake_set(key, items, *, ttl):
        stored[key] = items

    monkeypatch.setattr(
        "app.services.duplicate_wp_corpus_cache._cache_set",
        _fake_set,
    )

    def _fake_get_after_store(key):
        return stored.get(key)

    calls = {"n": 0}

    def _cache_get_tracked(key):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return stored.get(key)

    monkeypatch.setattr(
        "app.services.duplicate_wp_corpus_cache._cache_get",
        _cache_get_tracked,
    )

    get_live_site_articles_cached(
        user_id=1, target_website="https://ex.test", search_keywords=["sửa máy tính quận 9"]
    )
    get_live_site_articles_cached(
        user_id=1, target_website="https://ex.test", search_keywords=["sửa máy tính quận 9"]
    )
    m = wp_metrics()
    assert fetch_calls["n"] == 1
    assert m["wp_cache_hit"] >= 1


def test_wp_incremental_patch_and_invalidate(monkeypatch):
    monkeypatch.setenv("DUPLICATE_WP_CORPUS_CACHE", "1")
    ref = _ref("new post", url="https://ex.test/new", wp_post_id=99)
    patch_wp_corpus_post(user_id=5, site="https://ex.test", post_id=99, ref=ref)
    invalidate_wp_corpus_for_site(user_id=5, site="https://ex.test")
    d = ref_to_dict(ref)
    assert ref_from_dict(d).keyword == "new post"


def test_async_wp_refresh_enqueued(monkeypatch):
    monkeypatch.setenv("DUPLICATE_WP_CORPUS_CACHE", "1")
    monkeypatch.setenv("DUPLICATE_WP_ASYNC_FETCH", "1")
    enqueued: list[dict] = []

    def _fake_enqueue(**kwargs):
        enqueued.append(kwargs)

    monkeypatch.setattr(
        "app.services.duplicate_wp_corpus_cache._enqueue_refresh",
        _fake_enqueue,
    )
    monkeypatch.setattr(
        "app.services.content_ai_duplicate_detection._collect_live_site_articles",
        lambda **kw: [_ref("x", url="https://ex.test/x")],
    )
    stale_refs = [_ref("stale", url="https://ex.test/stale")]

    def _cache_get(key):
        if str(key).endswith(":stale"):
            return stale_refs
        return None

    monkeypatch.setattr("app.services.duplicate_wp_corpus_cache._cache_get", _cache_get)
    monkeypatch.setattr("app.services.duplicate_wp_corpus_cache._cache_set", lambda *a, **k: None)

    out = get_live_site_articles_cached(
        user_id=2, target_website="https://ex.test", search_keywords=["x"]
    )
    assert len(out) == 1
    assert enqueued


def test_duplicate_output_regression_same_thresholds(monkeypatch):
    corpus = [_ref("home computer repair in District 9", title="Home repair D9")]
    monkeypatch.setattr(
        "app.services.content_ai_duplicate_detection.collect_existing_articles",
        lambda **kw: corpus,
    )
    monkeypatch.setattr(
        "app.services.duplicate_wp_corpus_cache.get_live_site_articles_cached",
        lambda **kw: [],
    )
    monkeypatch.setattr(
        "app.services.content_ai_duplicate_detection.embed_keywords",
        lambda keywords, **kw: {},
    )
    rows = check_keywords_for_duplicates(
        ["trusted computer repair in District 9"],
        user_id=1,
        db=None,
    )
    assert rows[0]["is_duplicate"] is True
    assert rows[0]["match_type"] == "same_intent"
    assert rows[0]["message"] == MSG_SAME_INTENT


def test_embedding_job_idempotent(monkeypatch):
    monkeypatch.setenv("CELERY_EMBEDDING_WORKER", "1")
    calls = {"n": 0}

    def _fake_local(keywords, *, tenant_scope="global", use_cache=True):
        calls["n"] += 1
        v = np.array([1.0, 0.0], dtype=np.float32)
        return {k: v for k in keywords}

    monkeypatch.setattr(
        "app.services.semantic_embedding.embed_keywords_local",
        _fake_local,
    )
    from app.workers.embedding_tasks import embed_keywords_task

    r1 = embed_keywords_task(["alpha", "beta"], "t1", "job-fixed-1")
    r2 = embed_keywords_task(["alpha", "beta"], "t1", "job-fixed-1")
    assert r1.get("ok")
    assert r2.get("ok")
    assert calls["n"] == 1 or r2.get("cached")


def test_concurrent_duplicate_checks(monkeypatch):
    corpus = [_ref(f"keyword {i}", title=f"Title {i}") for i in range(20)]
    monkeypatch.setattr(
        "app.services.content_ai_duplicate_detection.collect_existing_articles",
        lambda **kw: corpus,
    )
    monkeypatch.setattr(
        "app.services.duplicate_wp_corpus_cache.get_live_site_articles_cached",
        lambda **kw: [],
    )
    monkeypatch.setattr(
        "app.services.content_ai_duplicate_detection.embed_keywords",
        lambda keywords, **kw: {},
    )

    def _run(_):
        return check_keywords_for_duplicates(
            ["keyword 0", "unique phrase xyz"],
            user_id=99,
            db=None,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(_run, range(50)))
    assert all(len(r) == 2 for r in results)
    assert results[0][0]["is_duplicate"] is True


def test_wp_timeout_returns_stale(monkeypatch):
    monkeypatch.setenv("DUPLICATE_WP_CORPUS_CACHE", "1")
    from app.services.duplicate_wp_corpus_cache import (
        _cache_set,
        _corpus_key,
        _fetch_live_corpus_resilient,
    )

    cache_key = _corpus_key(user_id=1, site="https://ex.test", keywords=["kw"])
    stale = [_ref("stale", url="https://ex.test/stale")]
    _cache_set(cache_key, stale, ttl=60)

    def _boom(**kwargs):
        raise TimeoutError("wp timeout")

    monkeypatch.setattr(
        "app.services.content_ai_duplicate_detection._collect_live_site_articles",
        _boom,
    )
    refs, err = _fetch_live_corpus_resilient(
        user_id=1,
        target_website="https://ex.test",
        search_keywords=["kw"],
        role="user",
        cache_key=cache_key,
    )
    assert err is not None
    assert len(refs) == 1
