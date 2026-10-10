# WAVE 3 — DB / PgBouncer Hardening

**Snapshot:** 2026-09-02T03:08:12.295347+00:00  
**Result:** `WAVE_3_DB_PGBOUNCER = FULL PASS` (hardening + production validation)

| Phase | Report |
|-------|--------|
| Pool tuning + index audit | `wave3_report.json` |
| **Production validation** | `pgbouncer_production_report.json` |

## Production validation gates (evidence)

```text
PGBOUNCER_BUSINESS_LOAD_10/50/100 = PASS
TRANSACTION_POOL_COMPATIBILITY     = PASS
NO_POOL_EXHAUSTION                 = PASS
TENANT_QUERY                       = PASS
PGBOUNCER_ROLLBACK                 = PASS
PRODUCTION_LIVE                    = PASS
```

Run: `.venv/bin/python scripts/wave3_pgbouncer_production.py --apply-canary --with-rollback-drill`

Index WARN: see `INDEX_WARN.md` (`ix_wordpress_publish_jobs_status_created` — non-blocking).

**Post-validation:** PM2 restored to `DB_USE_PGBOUNCER=0` / direct `:5435`. Enable canary with `--keep-canary` after review.

## Before → Root cause → Fix → After

| # | Before | Root cause | Fix | After |
|---|--------|------------|-----|-------|
| 1 | pool_size=10, max_overflow=20 per process × ~21 processes → theoretical ~630 vs max_connections=100 | Connection budget | Per-role SQLAlchemy pools (web 3+3, worker 2+2, beat 1+1); optional PgBouncer NullPool | client_max≈78 ≤ PG max 100 |
| 2 | `list_entries_pg` loaded full `payload_json` on every list row | List payload bloat | `defer(payload_json)` — scalar columns remain authoritative for API | List queries skip large JSON blob |
| 3 | startup `options: -c statement_timeout` rejected by PgBouncer | PgBouncer connect | Omit options when `DB_USE_PGBOUNCER=1`; SET via connect event | PgBouncer smoke SELECT 1 PASS on :6433 |
| 4 | Missing composite indexes on generations/projects/credits | Hot paths indexes | ensure_wave3_db_indexes migration (3 applied; WP index needs table owner) | 80 indexes across 10 tables |

## Connection budget

- Uvicorn workers: 8
- Celery child processes (approx): 7
- Web per-process: `{'role': 'web', 'pgbouncer': False, 'pool_size': 3, 'max_overflow': 3, 'max_per_process': 6}`
- Worker per-process: `{'role': 'celery', 'pgbouncer': False, 'pool_size': 2, 'max_overflow': 2, 'max_per_process': 4}`
- Client theoretical max: **78**
- PostgreSQL / PgBouncer pool max: **100**

## DB Profile

| Metric | Before | After |
|--------|--------|-------|
| total_connections | 27 | 29 |
| active | 1 | 1 |
| idle | 26 | 28 |
| slow_queries_gt_1s | 0 | 0 |
| transactions_gt_5s | 0 | 0 |

## Load tests

- Pool exhaustion (40 concurrent): errors=0, elapsed=0.064s
- Concurrent mix (API+DB, n=24): api_ok=12, db_ok=12

## Rollback

Set `DB_USE_PGBOUNCER=0` and `DATABASE_URL` back to `127.0.0.1:5435`. `pm2 reload ecosystem.config.cjs --update-env`.

## Gates

- CONTENT_AI_DB_REGRESSION: **PASS**
- CREDIT_DB_REGRESSION: **PASS**
- DB_POOL: **PASS**
- INDEX_AUDIT: **PASS**
- NO_N_PLUS_ONE: **PASS**
- NO_POOL_EXHAUSTION: **PASS**
- PGBOUNCER: **PASS**
- PRODUCTION_READY: **PASS**
- SLOW_QUERY: **PASS**
- TENANT_QUERY: **PASS**
