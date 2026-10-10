# SEOAuto SaaS Cost Audit (Excel companion)

**UTC:** see `SUMMARY` sheet in `seoauto_saas_cost_audit.xlsx`  
**Scope:** read-only source + runtime — no code/UI/business logic changes  
**File:** `docs/baseline/saas_monetization_audit/seoauto_saas_cost_audit.xlsx`

## Sheets

1. `SUMMARY` — runtime snapshot + PASS/FAIL gates  
2. `FEATURE_COST` — all metered/unmetered features with real cost vs credit  
3. `TOP_10_EXPENSIVE` — FEATURE | REAL_COST | CURRENT_CREDIT | CURRENT_MARGIN | RECOMMENDED_CREDIT | OPTIMIZATION  
4. `CREDIT_MAPPING` — DB/code/runtime credits + reserve/commit/double/free/refund risks  
5. `PLAN_PROFITABILITY` — plans + credit packs vs 70% GM target  
6. `UNMETERED_FEATURES` — 0-credit surfaces + abuse vectors  
7. `OPTIMIZATION` — P0/P1/P2 actions  

## Assumptions

- FX: 25,000 VND/USD (`saas_economics_service`)  
- Credit sell floor: 100 VND/credit (`CREDIT_100K`)  
- Recommended credit: `ceil(real_cost × 1.25 / 0.30 / 100)` → markup ≈ 4.17× cost for ≥70% GM + 25% safety  

## Verdicts

```
SAAS_COST_MODEL = FAIL
CREDIT_MODEL = FAIL
PLAN_MARGIN_SAFE = FAIL
```

### Why FAIL

- **SAAS_COST_MODEL:** Packs sell 77–100 VND/cr while Places (~800 VND/scan), AI image (~975 VND), Claude-tier content can exceed pack economics; expensive APIs under-covered.  
- **CREDIT_MODEL:** Image `except: pass`; CSKH overage non-idempotent; cluster async commits before job success; WP/embedding/submit-index/crawl/email/storage at 0 credit.  
- **PLAN_MARGIN_SAFE:** Agency/Business included-credit liability at 300 VND/cr attribution goes negative; Basic worst GM ~62% < 70%.  

## TOP 10 (by REAL_COST avg VND)

See Excel `TOP_10_EXPENSIVE`. Headline: AI image runtime (2 cr vs ~975 VND), lead scan (12 vs ~800), chatbot image bundle, Places detail, DFS keyword paths, deep audit.

## Related

- Broader monetization write-up: `REPORT.md`  
