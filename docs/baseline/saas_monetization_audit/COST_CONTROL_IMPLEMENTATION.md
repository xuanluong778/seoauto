# Cost control implementation — PASS/FAIL

**UTC:** 2026-09-03  
**Constraint:** plan prices and included monthly credits unchanged. Content AI output/prompts/Facebook App Review untouched.

Assumptions: FX 25,000 VND/USD; pack floor 100 VND/credit (`CREDIT_100K`).

---

## Gates

```
CREDIT_ENGINE              PASS
QUOTA_ENGINE               PASS
UNMETERED_FEATURES         FAIL
AI_IMAGE_MARGIN            PASS
KEYWORD_RESEARCH_MARGIN    PASS
KEYWORD_CLUSTERING_MARGIN  PASS
PLAN_MARGIN_SAFE           FAIL
SAAS_COST_CONTROL          FAIL
```

`SAAS_COST_CONTROL` is FAIL because plan included-credit pools and remaining infra surfaces still miss the 70% GM / full-meter bar. Feature-level credit engine, quotas, image/KW/cluster prices, and the listed credit bugs are addressed.

---

## CREDIT_ENGINE — PASS

SSOT `app/services/credit_cost_registry.py` revision **5**, locked keys overwrite DB on boot via `ensure_cost_control_ssot`.

| Action | Credit |
|--------|--------|
| AI image | 50–55 (SSOT 52; catalog 50/52/53/55) |
| Lead scan | 42 (cache 50% discount, not zero) |
| Place detail | 22 |
| Deep research | 22 |
| Deep audit | 15 |
| Keyword research | 30 live / 5 cache (unchanged) |
| Cluster | 2–3 cr / 50 KW local; +9 cr / 50 KW SERP |
| WP publish | 3 |
| Index Google / IndexNow | 2 / 10 URLs ; 1 / 20 URLs |

Bugs closed: image `except: pass` → reserve→commit; CSKH overage stable idempotency; cluster commit **after** job; stale reservation release on boot; WP HTTP + plugin Celery + index submit metered.

Tests: `tests/test_cost_control_ssot.py` + cost-gate suite (43 passed in last run).

**Cutover:** restart app so boot hook overwrites live DB (`ai_image` was 15). Until then runtime DB can still undercharge.

---

## QUOTA_ENGINE — PASS

Plan prices/credits unchanged. Added monthly `keyword_cluster`: starter 20 / pro 60 / agency 150 / business 400. Daily/monthly user credit caps + provider daily caps + concurrency in `cost_control`. Synced on boot via `ensure_plan_quotas`.

---

## UNMETERED_FEATURES — FAIL

Now metered: WordPress publish, Google Indexing, IndexNow.

Still not charged on the live path: **crawl worker**, **transactional email**, **R2/storage**, **OpenAI embedding** (registry cost exists; fallback gated by `SEMANTIC_EMBEDDING_ALLOW_OPENAI=0`). In-quota CSKH replies remain 0 by design.

---

## AI_IMAGE_MARGIN — PASS

52 cr × 100 VND = 5,200 VND vs typical Gemini Flash Image ~500–1,000 VND (~80–90% GM). Band 50–55 covers catalog models. UI fallback if catalog omits CPI is 52 (was 2).

---

## KEYWORD_RESEARCH_MARGIN — PASS

Kept 30 cr live (~3,000 VND sell vs ~250 VND DataForSEO ≈ 92% GM). Cache 5 cr. DataForSEO daily task cap in cost control.

---

## KEYWORD_CLUSTERING_MARGIN — PASS

Charged by keyword blocks of 50. Local ST/TF-IDF default (OpenAI embed off unless env). SERP add-on 9 cr/block vs ~250 VND DFS (≥70% at 100 VND/cr). Monthly cluster quota per plan.

---

## PLAN_MARGIN_SAFE — FAIL (by constraint)

Included credits unchanged: Basic 500 / Pro 2,500 / Agency 7,000 / Business 18,000. Worst-case burn on Anthropic/Places/image still exceeds 70% GM on Pro+ (Agency/Business negative at 300 VND/cr attribution). Packs 77–100 VND/cr not retuned.

To PASS this gate later: raise pack VND/credit and/or shrink included pools (or raise plan prices).

---

## Admin Cost Dashboard

`gross_margin_pct` (today/month, target 70%), revenue vs estimated cost, top users, top orgs, feature burn — `saas_economics_service` + `admin-saas-economics.js`.

---

## Not done here

- Restart PM2 / live DB SSOT apply (boot does it on next start; can run `ensure_cost_control_ssot()` once).
- Crawl/email/R2 live metering.
- Pack price retune.
- Index Control TestClient 400/401 failures look CSRF/host related, not credit 402.
