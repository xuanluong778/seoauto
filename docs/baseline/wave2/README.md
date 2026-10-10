# WAVE 2 — Async LLM Architecture (2026-09-02)

## Kiến trúc

```
Browser → POST /content-ai/suggest-stream (unchanged URL + SSE format)
       → API tạo generation_id (idempotent) → PostgreSQL
       → Celery content_ai queue → worker chạy LLM
       → Redis stream (ordered chunks, TTL) → SSE bridge → Browser
       → PostgreSQL final result + billing (idempotent credit)
```

**Rollback:** `CONTENT_AI_ASYNC_GENERATION=0` → luồng sync cũ trong Uvicorn (không đổi UI).

## Feature flags (`shared/env.local`)

| Env | Mặc định | Mô tả |
|-----|----------|-------|
| `CONTENT_AI_ASYNC_GENERATION` | `0` | Bật async generation |
| `CONTENT_AI_ASYNC_ROLLOUT_PERCENT` | `0` | Canary 0–100% theo user bucket |
| `CONTENT_AI_ASYNC_SHADOW` | `0` | Shadow mode (log only, tương lai) |
| `QUEUE_GENERATION_PER_USER` | `2` | Concurrent gen / user+org |
| `QUEUE_GENERATION_GLOBAL` | `20` | Global concurrent cap |

### Rollout đề xuất

`Shadow → 5% → 10% → 25% → 50% → 100%`

```bash
# Canary 5%
CONTENT_AI_ASYNC_GENERATION=1
CONTENT_AI_ASYNC_ROLLOUT_PERCENT=5
pm2 reload ecosystem.config.cjs --update-env
```

## API (additive — UI không đổi)

| Endpoint | Mô tả |
|----------|-------|
| `POST /content-ai/suggest-stream` | Khi flag bật → async path, SSE contract giữ nguyên |
| `GET /content-ai/generations/{id}` | Poll status / reconnect |
| `GET /content-ai/generations/{id}/stream` | SSE reconnect (`?after_seq=N`) |
| `POST /content-ai/generations/{id}/cancel` | Cancel an toàn |

Query reconnect trên suggest-stream: `?generation_id=...&after_seq=N`

## States

`QUEUED → RUNNING → COMPLETED | FAILED | CANCELLED`

## Production Ready (2026-09-02) — `WAVE_2_ASYNC_LLM = FULL PASS`

Chạy validation:

```bash
PYTHONPATH=. .venv/bin/python scripts/wave2_production_ready.py
```

Báo cáo: `docs/baseline/wave2/wave2_production_ready_report.json`

### Gates bổ sung

| Gate | Result |
|------|--------|
| CONTENT_AI_OUTPUT_REGRESSION | **PASS** (24 tests — sync vs async SSE contract) |
| LOAD_10 | **PASS** |
| LOAD_25 | **PASS** |
| LOAD_50 | **PASS** |
| LOAD_100 | **PASS** |
| CANARY_ROLLOUT | **PASS** (5→10→25→50→100% bucket tolerance) |
| UI_REGRESSION | **PASS** |
| PRODUCTION_READY | **PASS** |

### Load test metrics (LOAD_100, infra thật PG+Redis)

| Metric | Value |
|--------|-------|
| error_rate | 0% |
| duplicate_jobs | 0 |
| duplicate_credits | 0 |
| queue_wait p50/p95 | ~7ms / ~700ms (enqueue burst) |
| total_duration p50/p95 | ~1.1s / ~2.2s |
| wall_clock (100 jobs, 20 parallel) | ~5.5s |
| DB connections (after) | ~25 |
| Redis memory | ~3.9M |
| Worker RAM | ~121MB each |

Load harness: 100 jobs queued → xử lý `min(N, QUEUE_GENERATION_GLOBAL=20)` parallel; LLM mocked (đo infra path, không burn API credit).

### Canary rollout verified

| Target | Actual (1000-user sample) |
|--------|---------------------------|
| 5% | 6.7% |
| 10% | 11.0% |
| 25% | 25.4% |
| 50% | 51.7% |
| 100% | 100.0% |

### Rollback policy

Nếu bất kỳ gate FAIL → script tự set `CONTENT_AI_ASYNC_GENERATION=0` + ghi `root_causes` trong report.

**Production hiện tại:** flag vẫn `OFF` — bật canary khi sẵn sàng:

```bash
CONTENT_AI_ASYNC_GENERATION=1
CONTENT_AI_ASYNC_ROLLOUT_PERCENT=5
```

---

## Gates — WAVE_2_ASYNC_LLM = PASS (core)

| Gate | Result |
|------|--------|
| CONTENT_AI_GENERATION | PASS |
| CONTENT_AI_STREAM | PASS |
| CONTENT_AI_OUTPUT_REGRESSION | PASS |
| STREAM_ORDERING | PASS |
| GENERATION_IDEMPOTENCY | PASS |
| CREDIT_IDEMPOTENCY | PASS |
| CLIENT_DISCONNECT_RECONNECT | PASS |
| CANCEL_GENERATION | PASS |
| AI_CONCURRENCY | PASS |
| QUEUE_RECOVERY | PASS |
| WORKER_CRASH_RECOVERY | PASS |
| MULTI_TENANT_ISOLATION | PASS |
| ASYNC_FLAG_ROLLBACK | PASS |
| UI_REGRESSION | PASS |
| KNOWN_FAILURES_NOT_INCREASED | PASS |

## Files mới / sửa

**Mới:**
- `app/models/content_ai_generation.py`
- `app/migrations/ensure_content_ai_generations.py`
- `app/services/content_ai_generation_{store,stream,service,runner}.py`
- `app/services/content_ai_async_rollout.py`
- `app/workers/content_ai_generation_tasks.py`
- `tests/test_wave2_content_ai_async.py`
- `scripts/wave2_async_llm.py`

**Sửa (Content AI only):**
- `app/routers/pages.py` — async branch + 3 endpoints
- `app/queue/celery_queues.py` — route `content_ai.run_generation`
- `app/queue/celery_app.py` — include worker
- `app/services/queue_fairness.py` — `generation` kind + org scope
- `app/workers/job_queue_recover.py` — recover stale generations

## Chạy validation

```bash
cd /var/www/seoauto_vn_usr/data/www/seoauto.vn-current
PYTHONPATH=. .venv/bin/python scripts/wave2_async_llm.py
PYTHONPATH=. .venv/bin/pytest tests/test_wave2_content_ai_async.py -q
```

## Load test (manual canary)

Tăng `CONTENT_AI_ASYNC_ROLLOUT_PERCENT` từng bước, đo tại 10/25/50/100 concurrent:
- queue wait, first-token latency, duration, error rate
- duplicate job/credit = 0
- CPU/RAM, Redis keys, DB connections

## Rollback

```bash
# env.local
CONTENT_AI_ASYNC_GENERATION=0
CONTENT_AI_ASYNC_ROLLOUT_PERCENT=0
pm2 reload /var/www/seoauto_vn_usr/data/www/shared/ecosystem.config.cjs --update-env
```

Không ảnh hưởng WordPress/Crawl/Email queues (task riêng `content_ai.run_generation` trên queue `content_ai`).
