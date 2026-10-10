# SEOAuto.vn SaaS Monetization & Credit Audit (READ-ONLY)

**Audit time (UTC):** 2026-09-03T05:37:47Z  
**Scope:** source + runtime DB/env only — no product code changes  
**App root:** `/var/www/seoauto_vn_usr/data/www/seoauto.vn-current`  
**FX assumption:** 1 USD = 25,000 VND (matches `saas_economics_service.DEFAULT_ECONOMICS_SETTINGS`)  
**Credit sell floor (pack):** ~77–100 VND/credit (`BILLING_CREDIT_PRODUCTS`)

---

## Verdicts

| Gate | Result | Primary reason |
|------|--------|----------------|
| `SAAS_MONETIZATION_SAFE` | **FAIL** | Credit packs sell below attributed/real cost of expensive APIs; refund leaves entitlement; unmetered burn surfaces |
| `CREDIT_MODEL_SAFE` | **FAIL** | Image debit `except: pass`; CSKH overage non-idempotent; async cluster commits before success; WP/crawl/embedding = 0 |
| `PLAN_PROFITABILITY` | **FAIL** | Agency/Business included-credit liability at high-cost burn exceeds plan revenue (gross margin target 70% not met) |

---

## 1. SAAS_ARCHITECTURE

Hybrid model: **subscription quota** (feature caps) + **credit wallet** (pay-per-API) + **credit/article packs**.

```
User → Checkout (VAT+10%) → SePay webhook → payment_orders
  → activate_product → subscription + grant plan credits / pack credits
User → Feature API → saas_action_gate / content_ai_credit_service
  → reserve → execute → commit|release → credit_ledgers + credit_ledger_entries
Workers (PM2/Celery): content_ai, wordpress, crawl, email, default, embedding
Third-party: OpenAI/OpenRouter/Anthropic/Gemini, DataForSEO, Google Places/CSE, R2
```

**Runtime:** 748 users; subscriptions `active=1`, `trialing=9`; paid orders `1` (110,000 VND); credit balances sum `5,098` across 16 users with balance>0.

---

## 2. PAYMENT_STACK

| Step | Evidence |
|------|----------|
| Catalog SKUs | `seoauto_pricing_catalog.py` / `saas_hybrid_pricing.py` — STARTER/PRO/AGENCY/BUSINESS `_M/_6M/_Y`, CREDIT_*, ARTICLE_ADDON_* |
| Checkout VAT | +10% on checkout (catalog/pricing services) |
| Webhook | `app/services/sepay_webhook_service.py` → paid order |
| Activation | `app/services/payment_activation_service.py` — `activate_product` idempotent skip-duplicate; grants plan cycle credits via `monthly_bonus_credit_service` / pack via `grant_credits` |
| Admin refund | `admin_billing_service.admin_refund_paid_order` — **marks order/tx refunded + affiliate clawback; does NOT reverse subscription entitlement** (explicit docstring L440) |

---

## 3. SUBSCRIPTION_STACK

| Item | Detail |
|------|--------|
| Paid plans | starter/Basic, pro, agency, business |
| Trial | `trial_3d` plan in DB (price 0); gates via `saas_trial_service` / `require_active_trial` |
| Free/demo | `free_trial_5d` BYOK low quota (`plan_quota_registry`) |
| Cycle credits | monthly = plan credits; semi-annual = 7× monthly; yearly = 14× monthly (`plan_cycle_credit_breakdown`) |
| Entitlement | `entitlement_service` + usage_limits from `PLAN_MONTHLY_QUOTAS` |
| Upgrade/downgrade | Via new SePay product activation (no mid-cycle proration engine found in audit path) |
| Expire | Subscription status + trial gates |

---

## 4. PLAN_TABLE

| Plan | Slug | Month VND | Credits/mo | AI articles quota | Lead scan | Chatbot replies |
|------|------|-----------|------------|-------------------|-----------|-----------------|
| Basic | starter | 399,000 | 500 | 30 | 30 | 500 |
| Pro | pro | 799,000 | 2,500 | 80 | 100 | 3,000 |
| Agency | agency | 1,690,000 | 7,000 | 200 | 300 | 15,000 |
| Business | business | 3,490,000 | 18,000 | 500 | 600 | 50,000 |
| Trial | trial_3d | 0 | 0 (buy credits) | limited | — | — |

Year ≈ 10× month price; +2 months bonus duration/credits. Semi-annual = pay 5 months, use 6 (+1 mo credit bonus).

**Credit packs:**

| Code | Price | Credits | VND/credit |
|------|-------|---------|------------|
| CREDIT_100K | 100,000 | 1,000 | 100.0 |
| CREDIT_300K | 300,000 | 3,300 | 90.9 |
| CREDIT_500K | 500,000 | 6,000 | 83.3 |
| CREDIT_1000K | 1,000,000 | 13,000 | 76.9 |

**Article addons:** 50/150k, 100/250k, 300/600k VND (≈3,000 / 2,500 / 2,000 VND per article slot).

---

## 5. CREDIT_LEDGER_FLOW

| Operation | Path |
|-----------|------|
| Grant | `credits.grant_credits` → `credit_ledger_entries` buckets + `credit_ledgers` + `users.credit_balance` |
| Consume | `consume_credits` / gate commit |
| Reserve | `credit_reservations` status reserved → committed/released |
| Admin grant | ledger reason `admin_grant` / `admin_plan_credit` / `admin_create_user` |
| Pack | `credit_pack_purchase` |
| Failed refund | reason `failed_refund` (1 runtime sample) |

**Runtime ledger reasons (top):** reserve technical_audit (−1130), content_ai_brief (−204), content_ai_article (−990), keyword_*, admin_grant (+3720), credit_pack_purchase (+1000).

Wallet = FIFO buckets in `credit_ledger_entries` + denormalized `users.credit_balance` (`credits.py`).

---

## 6. FEATURE_CREDIT_TABLE

Assumptions: pack sell floor **100 VND/credit**; USD=25k. Real cost = list-price estimate for typical call.

| FEATURE | CURRENT_CREDIT | REAL_COST_ESTIMATE (VND) | RECOMMENDED_CREDIT (≥70% GM @100 VND/cr) | RISK |
|---------|----------------|--------------------------|------------------------------------------|------|
| content_ai.article_short | 12 | ~40–800 (mini→sonnet) | 15 (mini) / 45 (sonnet path) | HIGH if Claude |
| content_ai.article_medium | 25 | ~60–1,400 | 25 / 70 | HIGH if Claude |
| content_ai.article_long | 45 | ~120–2,500 | 45 / 120 | HIGH if Claude |
| content_ai.addon_rewrite | 20 | ~½ article | +same ratio | HIGH |
| content_ai.addon_research | 15 | varies | 20 | MED |
| content_ai.addon_outline | 3 | low | 5 | LOW |
| content_ai.addon_internal_link | 5 | low/CPU | 5 | LOW |
| content_ai.brief_suggest | 2 | low | 3 | LOW |
| content_ai.ai_image (DB) | **15** (code default was 2) | ~500–1,500 | 40–50 | HIGH (margin ~35% @15) |
| content_ai.google_image | 8 | CSE low–med | 10 | MED |
| keyword.research_run | 30 | ~250 DFS | 15–20 | LOW (overcharged vs DFS alone) |
| keyword.dataforseo_live | 30 | ~250 | 15 | LOW |
| keyword.dataforseo_standard | 20 | ~250 | 15 | LOW |
| keyword.volume_batch_100 | 35 | scales w/ batch | 25–40 | MED |
| keyword.cluster_async | 2 | SERP/CPU | 8–15 if SERP | HIGH underpriced |
| keyword.cluster_sync | 3 | same | 8–15 | HIGH |
| keyword.cluster_save | 2 | storage | 1 | LOW |
| keyword.import_excel | 1 | CPU | 1 | LOW |
| keyword.intelligence / serp | 2–3 | med | 5–10 | MED |
| audit.technical_* | 3–10 | crawl/CPU | 8–15 | MED |
| seo_score.* | 2–3 | LLM small | 5 | MED |
| lead_scanner.basic_scan | 12 | ~800 Places | **40** | **P0 underpriced** |
| lead_scanner.place_detail | 11 | ~425 | **20** | HIGH |
| lead_scanner.geocode | 2 | low | 3 | LOW |
| lead_scanner.export | 8 | CPU | 5 | LOW |
| google_map.ai_generate | 2 | LLM | 5 | MED |
| schema.generate | 5 | LLM | 8 | MED |
| chatbot.images_bundle | 5 | image | 15 | HIGH |
| chatbot.internal_links | 3 | LLM | 5 | MED |
| chatbot_cskh.reply_overage | 2 | LLM | 5–8 | HIGH + idem bug |
| **wordpress.publish** | **0** | worker/egress | 2–5 | **P0 unmetered** |
| **crawl (worker)** | **0** | CPU/bandwidth | fold into audit or 1–3 | **P1** |
| **embedding** | **0** | OpenAI embed | 1–3 / batch | **P1** |
| email send | 0 (infra) | SMTP | soft-cap | P2 |
| R2/storage | 0 | Cloudflare | soft-cap | P2 |

---

## 7. THIRD_PARTY_COSTS

| Provider | Config / usage | Unit cost (est.) |
|----------|----------------|------------------|
| OpenAI | `OPENAI_MODEL=gpt-4o-mini`, image `gpt-image-1` | mini cheap; image expensive |
| OpenRouter | `openai/gpt-4o-mini`, image `google/gemini-2.5-flash-image` | flash-image ~$0.02–0.04 |
| Anthropic | via provider registry | Sonnet ~$3/$15 per MTok |
| DataForSEO | enabled, login set | ~$0.01/task typical |
| Google Places | lead scanner | search ~$0.032, detail ~$0.017 |
| Google CSE | `GOOGLE_CSE_ID` | per-query |
| R2 | plugin releases bucket | storage+egress |
| Redis | local 6380 | fixed |
| Postgres | Docker 5435 | fixed |
| Celery workers | 6 queues (+beat) | fixed CPU/RAM |

**Economics attribution (admin defaults, not sell price):** openai 250, anthropic 300, dataforseo 180, google_places 200, google_cse 150, crawl 50, other 100 VND/credit.

---

## 8. PLAN_PROFITABILITY

Liability method A = included credits × economics anthropic **300 VND/cr** (worst attribution).  
Target GM ≥ 70% ⇒ max liability ≤ 30% of plan price.

| PLAN | PRICE | INCLUDED_CREDIT | EST_COST_NORMAL* | EST_COST_MAX** | GROSS_MARGIN (max liability) | RISK |
|------|-------|-----------------|------------------|----------------|--------------------------------|------|
| Basic | 399k | 500 | ~50–125k | 150k | **62%** | FAIL <70% |
| Pro | 799k | 2,500 | ~150–400k | 750k | **6%** | FAIL |
| Agency | 1.69M | 7,000 | ~400k–1.0M | 2.10M | **−24%** | FAIL neg |
| Business | 3.49M | 18,000 | ~0.8–2.0M | 5.40M | **−55%** | FAIL neg |

\*Normal: mix gpt-4o-mini + DFS + light Places.  
\*\*Max: burn pool on Anthropic/Places/image paths.

**Credit packs at sell price vs attribution:** all packs **negative margin** vs openai 250 / anthropic 300 VND/cr economics.

---

## 9. CREDIT_BUGS

1. **Image debit swallowed:** `content_ai_content_images.py` + `pages.py` thumbnail — `except Exception: pass` after `consume_credits` → free images on debit failure.  
2. **CSKH overage idempotency:** `chatbot_cskh_credits.py` uses `new_request_id()` inside idem key → **every retry is unique** → double-charge risk.  
3. **Keyword cluster async:** `keywords.py` `sgate.commit()` **before** job success → failed job still charged (no automatic release path in enqueue).  
4. **Admin refund:** does not revoke subscription/credits already granted.  
5. **Stale reservations:** 2 `reserved` (40 cr) open in runtime — need watchdog reconciliation.

---

## 10. FEATURES_NOT_METERED

- WordPress publish / schedule workers  
- Embedding worker / vector pipeline  
- Raw crawl worker (beyond audit gate units)  
- In-quota CSKH replies (by design 0 until overage)  
- Email transactional  
- R2/object storage growth  
- Concurrent bulk Content AI within quota (credits still apply per article, but no hard concurrency $ cap beyond Celery concurrency)

---

## 11. DOUBLE_CHARGE / FREE_USAGE / REFUND_RISKS

| Risk | Type |
|------|------|
| Image `except: pass` | FREE_USAGE |
| WP/crawl/embedding 0 | FREE_USAGE / infra abuse |
| Cluster commit-before-job | NO_REFUND on FAIL |
| CSKH overage fresh request_id | DOUBLE_CHARGE |
| Admin refund without entitlement reverse | REFUND_RISK (user keeps plan) |
| Content AI hold+release on system fail | mostly OK (`failed_refund` seen) |
| Async jobs with reserve→commit on success | preferred pattern; cluster violates |

---

## 12. P0 / P1 / P2 ISSUES

### P0
- Credit pack sell price (~77–100 VND/cr) incompatible with Places/Anthropic/image real costs → pack buyers can destroy margin.  
- Lead scan 12 cr vs ~800 VND Places cost (GM ~33%).  
- Admin refund leaves subscription active.  
- Image charge failures silently ignored.

### P1
- Agency/Business credit pools oversized vs price (negative worst-case GM).  
- Cluster async commit-before-complete.  
- CSKH overage non-idempotent.  
- Embedding + WP publish unmetered.  
- Claude/premium model paths same credit as mini.

### P2
- Soft caps for email/R2/storage.  
- Economics dashboard settings not persisted in DB table (defaults only).  
- Reservation watchdog for stuck `reserved`.

---

## 13. RECOMMENDED_PLAN_PRICING

Keep list prices; **cut included credits** and/or raise price so liability ≤30% revenue at high-cost burn:

| Plan | Keep price | Max credits @300 VND/cr for 70% GM | Recommended credits/mo |
|------|------------|------------------------------------|-------------------------|
| Basic | 399k | ≤399 | **350–400** (or keep 500 if force mini-only) |
| Pro | 799k | ≤799 | **700–1,200** (cut from 2,500) |
| Agency | 1.69M | ≤1,690 | **1,500–2,500** (cut from 7,000) |
| Business | 3.49M | ≤3,490 | **3,000–5,000** (cut from 18,000) |

Alternatively: raise Agency→~2.5M+, Business→~6M+ if keeping large pools. Prefer **credit cut + model tiering** over sticker shock.

---

## 14. RECOMMENDED_CREDIT_PRICING

| Change | Recommendation |
|--------|----------------|
| Pack floor | **≥350–400 VND/credit** sell (e.g. 100k → 250–300 credits, not 1,000) |
| Volume packs | Do not deepen discounts below floor |
| Feature table | Apply FEATURE_CREDIT_TABLE recommended column |
| Model multiplier | Claude/Sonnet/Opus ×2–3 vs mini |
| Image | 40–50 cr / image (or pass-through OpenRouter $ × markup) |
| Lead scan | 40 cr search / 20 cr detail |
| WP publish | 2–5 cr |
| Embedding batch | 1–3 cr |

---

## 15. BREAK_EVEN_ANALYSIS

Per user/month fixed share (rough, VPS 31GB RAM single node):  
Infra fixed ~$80–150/mo → **~2–4M VND** → at 100 paying users ~20–40k VND/user fixed.

Break-even variable:  
`revenue ≥ 1.43 × (API + worker + storage)` for 70% GM ⇒ contribution ratio cost/revenue ≤ 0.30.

**Pack break-even:** sell_vnd_per_credit ≥ (real_api_vnd / credits_charged) / 0.30.  
For Places scan: 800 / 0.30 ≈ 2,667 VND revenue needed → at 100 VND/cr need **≥27 credits** (recommend 40).

**Plan break-even (70% GM):** included_credit × avg_real_cost_per_credit ≤ 0.30 × plan_price.

---

## 16. MONTHLY_COST_SIMULATION

Assumptions: mix 70% Basic / 20% Pro / 8% Agency / 2% Business; normal burn 40% of included credits; API mix mini-heavy (avg ~80 VND real cost/credit); infra fixed 3M VND + 5k VND/active user.

| Paying users | Sub revenue (blend ~650k ARPU*) | Credit liability cost | Infra | Est. total cost | Est. GM |
|--------------|----------------------------------|----------------------|-------|-----------------|---------|
| 100 | ~65M | ~8–12M | ~3.5M | ~12–16M | ~75–80% **if** mini mix |
| 1,000 | ~650M | ~80–120M | ~8M | ~90–130M | ~80% normal |
| 10,000 | ~6.5B | ~0.8–1.2B | ~50M | ~0.9–1.3B | fragile if 10%+ switch to Claude/Places max burn |

\*Rough blend of plan prices.  
**Worst-case 10% Agency/Business max-burn:** GM collapses; at 10k users can go **cash negative** on API alone.

---

## 17. FILES_AND_CODE_PATHS (evidence)

| Area | Paths |
|------|-------|
| Hybrid plans | `app/services/saas_hybrid_pricing.py` |
| Catalog / packs | `app/services/seoauto_pricing_catalog.py` |
| Quotas | `app/services/plan_quota_registry.py` |
| Credits core | `app/services/credits.py` |
| Cost registry | `app/services/credit_cost_registry.py` (+ DB `credit_cost_configs`) |
| Content AI billing | `app/services/content_ai_credit_service.py` |
| Gate | `app/services/saas_gate.py` |
| SePay / activate | `app/services/sepay_webhook_service.py`, `payment_activation_service.py` |
| Admin refund | `app/services/admin_billing_service.py` L431+ |
| Economics | `app/services/saas_economics_service.py` |
| Image free-on-fail | `app/services/content_ai_content_images.py` L163–175; `app/routers/pages.py` L1560–1574 |
| CSKH overage | `app/services/chatbot_cskh_credits.py` L107–126 |
| Cluster commit early | `app/routers/keywords.py` L1158–1170 |
| LLM providers | `app/services/content_ai_llm_providers.py`, env OpenRouter/OpenAI |
| Workers | `app/queue/celery_app.py`, PM2 workers |
| Runtime DB | `plans`, `credit_cost_configs`, `credit_ledgers`, `credit_reservations`, `subscriptions`, `payment_orders`, `users` |

---

## Conclusions

```
SAAS_MONETIZATION_SAFE = FAIL
CREDIT_MODEL_SAFE = FAIL
PLAN_PROFITABILITY = FAIL
```

**Why FAIL:** Pack unit economics sell credits cheaper than expensive API burn; large plans grant credit pools that can exceed revenue under Anthropic/Places/image mix; several high-cost or unmetered surfaces (Places underpriced, images silent fail, WP/embedding 0, cluster pre-commit, refund without revoke) break the 70% GM + safe metering requirements.

**No code was modified.** Next step (when requested): implement P0 pricing/metering fixes only.
