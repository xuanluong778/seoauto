# WAVE 3 — PgBouncer Production Validation

**Result:** `FAIL`
**Snapshot:** 2026-09-06T07:52:12.940302+00:00

## Gates

- NO_POOL_EXHAUSTION: **PASS**
- PGBOUNCER_BUSINESS_LOAD_10: **PASS**
- PGBOUNCER_BUSINESS_LOAD_100: **PASS**
- PGBOUNCER_BUSINESS_LOAD_50: **PASS**
- PGBOUNCER_ROLLBACK: **SKIP**
- PRODUCTION_LIVE: **PASS**
- TENANT_QUERY: **FAIL**
- TRANSACTION_POOL_COMPATIBILITY: **PASS**

## Index WARN

- `ix_wordpress_publish_jobs_status_created`: **WARN**
  - digiseo is not table owner — cannot CREATE INDEX; use table owner or DBA
  - Fallback `ix_wordpress_publish_jobs_status_retry` present: True

## Rollback

`DB_USE_PGBOUNCER=0` + `DATABASE_URL` → `:5435` + `pm2 reload ecosystem.config.cjs --update-env`

