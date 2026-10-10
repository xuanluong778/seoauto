# Cost control gates — final (UNMETERED / PLAN_MARGIN / SAAS_COST_CONTROL)

**UTC cutover:** 2026-09-03  
**SSOT revision:** 6

## Gates

```
UNMETERED_FEATURES   PASS
PLAN_MARGIN_SAFE     PASS
SAAS_COST_CONTROL    PASS
```

---

## UNMETERED_FEATURES — PASS

| Surface | BEFORE | AFTER |
|---------|--------|-------|
| Crawl Celery `process_crawl_job` | no usage/cost | `record_infra_cost_usage` feature=`crawl_job`, credits=0, estimated_cost≈80×pages, provider=`crawl`, request_id=`crawl:{job_id}:{retry}` + org/user from job |
| Transactional email `send_email` | no meter | usage log feature=`email_user_notify` (OTP `meter=False`); CSKH notify passes user_id/org |
| User storage `save_private_image` | no meter | feature=`storage_put`, bytes in metadata, provider=`local_disk` |
| R2 `S3StorageAdapter` put/get/stream | no meter | structured + optional DB log (`r2_put`/`r2_get`) |

Metadata always includes: `organization_id`, `feature_key`, `quantity`, `estimated_cost`, `provider`, `request_id`.

Registry: `storage.put/r2_*` credit_cost=0 (usage-only); crawl/email costs remain in SSOT.

---

## PLAN_MARGIN_SAFE — PASS (hard caps; plan prices unchanged)

Model: `cost = H×250 + (C−H)×50` VND ≤ 30% of month price (GM≥70%).  
Pack floor 77–100 VND/cr reported as liability reference only (not API COGS).

| Plan | Price | Credits | Expensive H | Worst cost | Max@70% | GM | BEFORE | AFTER |
|------|-------|---------|-------------|------------|---------|-----|--------|-------|
| Basic | 399k | 500 | 450 | 115k | 119.7k | 71.2% | FAIL (~62%) | **PASS** |
| Pro | 799k | 2,500 | 560 | 237k | 239.7k | 70.3% | FAIL (~6%) | **PASS** |
| Agency | 1.69M | 7,000 | 780 | 506k | 507k | 70.1% | FAIL (−24%) | **PASS** |
| Business | 3.49M | 18,000 | 720 | 1.044M | 1.047M | 70.1% | FAIL (−55%) | **PASS** |

Monthly expensive credit caps (enforced in `cost_gate` + `saas_action_gate`):

| | ai_image | places_lead | dataforseo_live | premium_llm |
|--|----------|-------------|-----------------|-------------|
| starter | 150 | 150 | 100 | 50 |
| pro | 200 | 160 | 120 | 80 |
| agency | 260 | 220 | 180 | 120 |
| business | 240 | 200 | 160 | 120 |

No plan price / included-credit change. Pack prices unchanged.

---

## SAAS_COST_CONTROL — PASS

| Criterion | Evidence |
|-----------|----------|
| Metered features (incl. crawl/email/storage) | hooks + registry + tests |
| Cost caps | daily credit/provider + expensive monthly categories |
| Plan worst-case GM ≥70% | `evaluate_all_plan_margins().all_pass` |
| Idempotency / no double-charge | prior CREDIT_ENGINE fixes retained (reserve→commit, CSKH key, cluster after job) |

---

## Ops

1. `ensure_cost_control_ssot` revision 6 (storage keys).  
2. Restart PM2 web + workers to load code and clear credit cache.  
3. Tests: `tests/test_plan_margin_and_infra_meter.py` + cost-control suite.
