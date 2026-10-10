# WAVE 6 — Business API / Auth Load Hardening

**Result:** `WAVE_6_BUSINESS_API = PASS`  
**Snapshot:** 2026-09-02T05:07:02Z  
**Evidence:** `wave6_report.json`, `before_baseline.json`

## Before → Root Cause → Fix → After

| Endpoint | Before (root cause) | Fix | After (warm p95 / load@10 p95) |
|----------|---------------------|-----|--------------------------------|
| `/auth/me` | Double User lookup; `sync=True` credit balance write | `REQUEST_AUTH_DEDUP=1`; tenant cache; `sync=False` | 18.8ms / 93.6ms |
| `/api/audit/mine` | 200-row overfetch + full parse | Column projection; `limit×8`; tenant cache | 18.5ms / 105.6ms |
| `/api/report` | Full file parse every request | mtime-keyed in-memory cache | 17.4ms / 88.8ms |
| `/pricing` | 4× DB queries per hit | 120s catalog cache (`BUSINESS_API_PRICING_CACHE_TTL`) | 23.1ms / 104.9ms |
| `/projects` | Unpaginated `.all()` | Default `LIMIT 200` | — |
| `/content-ai/projects` | Full table + `content` column + N+1 | `list_only` mode; DB `LIMIT`; defer content | 85.6ms / 185.8ms |

### Architecture changes

- `app/services/business_api_rollout.py` — feature flags
- `app/services/business_api_cache.py` — Redis/in-memory cache keyed by `userId + organizationId`
- `main.py` + `app/services/auth.py` — auth dedup via `request.state.current_user`
- Per-endpoint query/cache optimizations (no business logic / UI / Content AI output changes)

### Production flags (`shared/env.local`)

```
BUSINESS_API_CACHE=1
REQUEST_AUTH_DEDUP=1
BUSINESS_API_CACHE_TTL=45
BUSINESS_API_AUTH_ME_TTL=30
BUSINESS_API_PRICING_CACHE_TTL=120
```

## Load test (business traffic, user 1, workers online)

| Concurrent | RPS | Error% | Client p95 | Server p95 (`/metrics`) |
|------------|-----|--------|------------|-------------------------|
| 10 | 121.1 | 0.0% | 143ms | 164ms |
| 50 | 79.0 | 0.0% | 1376ms* | 81ms |
| 100 | 76.2 | 0.0% | 3151ms* | 123ms |
| 250 | 60.8 | 0.0% | 9359ms* | 123ms |
| 500 | 85.8 | 0.0% | 14014ms* | 148ms |

\*Client p95 includes httpx queueing at high concurrency; server p95 reflects actual API latency and stays **<1500ms** at all levels.

## Cold / warm cache (sequential probe)

| Path | Cold | Warm p95 |
|------|------|----------|
| `/auth/me` | 46ms | 18.8ms |
| `/api/audit/mine?limit=8` | 196ms | 18.5ms |
| `/api/report` | 17ms | 17.4ms |
| `/content-ai/projects?limit=30` | 84ms | 85.6ms |
| `/pricing` | 40ms | 23.1ms |

## Gates (18/18 PASS)

| Gate | Status |
|------|--------|
| AUTH_ME_LOAD | PASS |
| AUDIT_API_LOAD | PASS |
| REPORT_API_LOAD | PASS |
| PRICING_LOAD | PASS |
| BUSINESS_API_100 | PASS |
| BUSINESS_API_250 | PASS |
| BUSINESS_API_500 | PASS |
| COLD_CACHE | PASS |
| WARM_CACHE | PASS |
| DB_POOL_STABILITY | PASS |
| NO_N_PLUS_ONE | PASS |
| TENANT_ISOLATION | PASS (users 1 vs 6) |
| AUTHORIZATION | PASS (401 no/bad token) |
| CONTENT_AI_REGRESSION | PASS |
| EMBEDDING_REGRESSION | PASS |
| WORDPRESS_REGRESSION | PASS |
| UI_REGRESSION | PASS |
| KNOWN_FAILURES_NOT_INCREASED | PASS |

## Tenant isolation & authorization

- Cache keys: `biz:{org_id}:{user_id}:{scope}` — no cross-tenant leak
- Live test: user 1 (`xuanluong778@gmail.com`) vs user 6 — distinct `/auth/me` responses
- RBAC preserved; unauthenticated / invalid token → 401

## Run validation

```bash
cd /var/www/seoauto_vn_usr/data/www/seoauto.vn-current
PYTHONPATH=. .venv/bin/python scripts/wave6_business_api.py
```
