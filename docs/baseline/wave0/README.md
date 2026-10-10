# WAVE 0 — Baseline Snapshot

Snapshot thời điểm: **2026-09-01** (UTC+7)

Tuân thủ `docs/nguyen-tac-lap-trinh.md`: chỉ ghi nhận trạng thái hiện tại, **không đổi UI/API/Content AI output**.

## Gates

| Gate | Kết quả | Ghi chú |
|------|---------|---------|
| `BASELINE` | **FAIL** | 1463 passed / **56 failed** / 1 skipped (1520 tests, ~8m53s) |
| `UI_BASELINE` | **PASS** | 16/16 trang snapshot OK |
| `CONTENT_AI_BASELINE` | **PASS** | 7 luồng core: **65/65** tests PASS |

## Artifacts

| File | Mô tả |
|------|--------|
| `wave0_report.json` | Tổng hợp gates + metrics |
| `pytest_full.log` | Full test run |
| `junit_full.xml` | JUnit full suite |
| `pytest_content_ai.log` | Content AI targeted run |
| `ui_pages_snapshot.json` | SHA256 + title + markers mỗi trang |
| `api_contracts_content_ai.json` | 11 endpoint Content AI contract |
| `openapi_full.json` | 652 paths OpenAPI |
| `openapi_content_ai.json` | 111 paths `/content-ai/*` |
| `infra_metrics.json` | CPU/RAM/DB/Redis/PM2 |

## Chạy lại

```bash
cd /var/www/seoauto_vn_usr/data/www/seoauto.vn-current
source /var/www/seoauto_vn_usr/data/www/shared/env.local
export PYTHONPATH=$PWD
.venv/bin/python scripts/wave0_baseline.py
```

## UI pages (sha256)

| Path | Status | SHA256 (16 ký tự đầu) |
|------|--------|------------------------|
| `/content-ai` | 200 | `adf92ec76d4fd274` |
| `/tool` | 200 | `8410a946b1f3e3d4` |
| `/chatbot-cskh` | 200 | `8ef4a05490ac530e` |
| `/social-auto` | 200 | `0663d7c5ce5ebeee` |
| `/settings` | 200 | `a02e47fbb54f3e32` |
| `/pricing` | 200 | `5ddaa9daed731ace` |
| `/account-billing` | 200 | `7259c92200cb9316` |
| `/admin/*` | 302 → `/settings#account` | (empty body) |

## Infra @ snapshot

- CPU: 8 cores, loadavg ~2.28
- RAM available: ~20.5 GB / 31 GB
- DB connections: 57, size ~24 MB
- Redis: 3965 keys, queue depth 0
- PM2: seoauto-web (8 workers), seoauto-worker, seoauto-email-beat

## Content AI flows tested

- suggest-stream, draft, regenerate → `test_content_ai_e2e_audit_fixes.py`
- duplicate-check → `test_content_ai_duplicate_detection.py`
- credit → `test_content_ai_credit.py`
- bulk → `test_content_ai_bulk_progress.py`, `test_bulk_celery_no_inline_dup.py`
- WordPress publish → `test_wp_publish_draft.py`, e2e WP guard

**Lưu ý:** `test_content_ai_publish_schedule.py` có 4 errors (FK `payment_orders` khi `create_all` SQLite) — không thuộc 7 luồng gate trên.
