# WAVE 7 — Full System Mixed Load & Soak

**Result:** `WAVE_7_FULL_SYSTEM_STABILITY = FULL PASS`
**Final pass:** 2026-09-02 (2h soak + security gates)
**Evidence:** `wave7_report.json`, `soak_2h_timeseries.jsonl`, `before_baseline.json`

## Summary

| Phase | Result |
|-------|--------|
| Mixed load 50→500 | PASS (0% 5xx) |
| Soak 100/250 × 30m | PASS |
| Soak 100 × 2h | PASS (646k req, 89.7 rps) |
| Security (XFF/rate limit) | PASS |
| Stability (memory/conn/queue/worker) | PASS |

## 2h soak evidence

| Metric | Value |
|--------|-------|
| Duration | 7200s (2h) |
| Requests | 646,132 |
| RPS | 89.7 |
| Error (5xx only) | **0%** |
| Policy responses (402/403/429) | ~3.1% (expected synthetic load) |
| RAM growth | +54.6 MB (+27 MB/h) |
| DB connections | 24 → 22 |
| Queue after drain | 0 |
| Worker restarts during soak | 0 |

## Security gates

| Gate | Status |
|------|--------|
| TRUSTED_PROXY_XFF | PASS — `TRUSTED_PROXY_XFF=1`, pytest |
| XFF_SPOOF_PROTECTION | PASS — untrusted peer ignores spoofed XFF |
| RATE_LIMIT_EXPECTED_429 | PASS — single IP hits 429 at /analyze limit |
| REAL_MULTI_USER_LOAD | PASS — 12 users, 0% 5xx |

## Fix: trusted proxy XFF

- **Before:** `_client_ip` trusted any client-supplied `X-Forwarded-For` → spoof bypass
- **After:** `app/services/trusted_proxy.py` — only trust X-Real-IP/XFF when peer is nginx (`127.0.0.1`)
- **Flag:** `TRUSTED_PROXY_XFF=1` in `shared/env.local`

## All gates

See `wave7_report.json` → `gates` (26 gates, all PASS)

## Run

```bash
# Full validation including 2h soak (~2h)
PYTHONPATH=. .venv/bin/python scripts/wave7_full_system.py --final-pass

# Reconcile 2h report after gate definition update
PYTHONPATH=. .venv/bin/python scripts/wave7_reconcile_2h.py
```
