# WAVE 1 — Celery Scale (2026-09-02)

## Mục tiêu đạt được

- Tách queue: `content_ai`, `wordpress`, `crawl`, `email`, `default`
- Prefork thay solo (5 PM2 worker apps, không còn `seoauto-worker` solo)
- Job claim CAS PostgreSQL (`claim_job_by_id` + stress test 20 threads)
- Retry/backoff WP publish, recovery beat, fairness slots giữ nguyên logic hiện tại
- Không đổi UI / API contract / Content AI output

## Pre-flight

| Check | Kết quả |
|-------|---------|
| Backup script | PASS — `scripts/backup/backup_seoauto.sh` |
| Backups gần nhất | `/var/www/seoauto_vn_usr/data/backups/` (wave0–wave4) |
| KNOWN_FAILURES_WAVE0 | `docs/baseline/wave0/KNOWN_FAILURES_WAVE0.txt` (56 entries) |
| UI_BASELINE | PASS (5/5 pages HTTP 200) |
| CONTENT_AI_BASELINE | PASS (63/63 tests) |

## PM2 workers (production)

| Process | Queue | Pool | Concurrency |
|---------|-------|------|-------------|
| seoauto-worker-content-ai | content_ai | prefork | 2 |
| seoauto-worker-wordpress | wordpress | prefork | 1 |
| seoauto-worker-crawl | crawl | prefork | 2 |
| seoauto-worker-email | email | prefork | 1 |
| seoauto-worker-default | default | prefork | 1 |
| seoauto-email-beat | — | beat | 1 |

Feature flag: `CELERY_MULTI_QUEUE=1` trong `shared/env.local`.

Rollback: đặt `CELERY_MULTI_QUEUE=0` và `pm2 reload ecosystem.config.cjs` → quay về 1 worker solo.

## Gates (scale 1 → 2 → 4)

| Gate | L1 | L2 | L4 |
|------|----|----|-----|
| CELERY_QUEUE | PASS | PASS | PASS |
| CELERY_PREFORK | PASS | PASS | PASS |
| JOB_CLAIM_CONCURRENCY | PASS | PASS | PASS |
| NO_DUPLICATE_JOB | PASS | PASS | PASS |
| QUEUE_RECOVERY | PASS | PASS | PASS |
| CREDIT_IDEMPOTENCY | PASS | PASS | PASS |
| CONTENT_AI_BULK_REGRESSION | PASS | PASS | PASS |
| WP_PUBLISH_REGRESSION | PASS | PASS | PASS |
| UI_REGRESSION | PASS | PASS | PASS |
| KNOWN_FAILURES_NOT_INCREASED | PASS | PASS | PASS |

**Overall: PASS** tại cả 3 mức scale.

Báo cáo chi tiết:
- `wave1_report.json` — scale mặc định
- `wave1_scale1_report.json` — content_ai=1, crawl=1
- `wave1_scale2_report.json` — content_ai=2, crawl=2 (production)
- `wave1_scale4_report.json` — content_ai=4, crawl=4 (stress)

## Metrics snapshot (scale 2 — production)

| Metric | Value |
|--------|-------|
| QUEUE_DEPTH (all queues) | 0 |
| DB_CONNECTIONS | ~19 |
| REDIS keys | ~2685 |
| FAILED (regression subset) | 0 new vs KNOWN_FAILURES |
| DUPLICATED | 0 (PG claim test) |

## Files thay đổi

- `app/queue/celery_queues.py` — routing + queue definitions
- `app/queue/celery_app.py` — prefork settings, `task_reject_on_worker_lost`
- `app/workers/wordpress_publish_worker.py` — retry backoff
- `app/workers/wordpress_phase2_worker.py` — retry backoff
- `shared/ecosystem.config.cjs` — 5 prefork workers
- `shared/env.local` — `CELERY_MULTI_QUEUE=1` + concurrency
- `scripts/wave1_celery_scale.py` — validation script
- `tests/test_wave1_celery_queues.py`
- `tests/test_wave1_job_claim_concurrency_pg.py`

## Chạy lại validation

```bash
cd /var/www/seoauto_vn_usr/data/www/seoauto.vn-current
PYTHONPATH=. .venv/bin/python scripts/wave1_celery_scale.py --scale-level 2
```

## Rollback nếu gate FAIL

```bash
# env.local
CELERY_MULTI_QUEUE=0

pm2 delete seoauto-worker-content-ai seoauto-worker-wordpress seoauto-worker-crawl seoauto-worker-email seoauto-worker-default
pm2 reload /var/www/seoauto_vn_usr/data/www/shared/ecosystem.config.cjs --update-env
```
