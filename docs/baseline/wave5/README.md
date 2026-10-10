# WAVE 5 — Embedding / Duplicate Check

**Result:** `WAVE_5_EMBEDDING_DUPLICATE = FULL PASS`
**Snapshot:** 2026-09-02T04:23:46.748781+00:00

## Architecture

- Uvicorn: duplicate-check API only; no sentence-transformers load when `EMBEDDING_CELERY_WORKER=1`
- `seoauto-worker-embedding`: `embedding.embed_keywords` + `duplicate.sync_wp_corpus`
- Cache: `emb:v2:{tenant}:{content_hash}` + `dup:wp:{user}:{site}:{kw_sig}`

## Gates

- ASYNC_WP_FETCH: **PASS**
- CACHE_INVALIDATION: **PASS**
- COLD_CACHE: **PASS**
- DUPLICATE_CHECK: **PASS**
- DUPLICATE_OUTPUT_REGRESSION: **PASS**
- EMBEDDING_CACHE: **PASS**
- EMBEDDING_MEMORY: **PASS**
- KNOWN_FAILURES_NOT_INCREASED: **PASS**
- LARGE_CORPUS: **PASS**
- LIVE_WP_CORPUS: **PASS**
- LOAD_100: **PASS**
- PRODUCTION_FLAGS: **PASS**
- ROLLBACK: **PASS**
- TENANT_ISOLATION: **PASS**
- WARM_CACHE: **PASS**
- WP_429_500_RECOVERY: **PASS**
- WP_FETCH: **PASS**
- WP_INCREMENTAL_SYNC: **PASS**
- WP_TIMEOUT_RECOVERY: **PASS**

## Load test

- 1 concurrent: 75.4ms p95
- 10 concurrent: 567.6ms p95
- 50 concurrent: 1939.4ms p95
- 100 concurrent: 2579.4ms p95

## WP fetch (mock audit)

- fetch_count (audit): 1
- cache_hit: 1

## Live WordPress

- Site: https://itsieuviet.com
- Cold latency: 10745.6ms
- Warm p95: 2.2ms
- Large corpus (24 kw): 8 refs in 57092.2ms

## System

- Redis: 4.85M
- Embedding queue depth: 0
- Embedding p95 wait: 2.3ms
