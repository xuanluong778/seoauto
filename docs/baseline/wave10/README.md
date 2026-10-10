# WAVE 10 — UI / API / Content AI regression

**Result:** `WAVE_10_UI_REGRESSION = PASS`  
**Compared against:** `docs/baseline/wave0/ui_pages_snapshot.json` (pre-upgrade HTML baseline)  
**Runtime:** Playwright Chromium + live HTTP `http://127.0.0.1:8899`

## Gates

| Gate | Result | Evidence |
|------|--------|----------|
| UI_REGRESSION | **PASS** | SHA256 HTML = WAVE 0 on 16/16 pages; 14 Playwright screenshots; E2E clicks |
| API_COMPATIBILITY | **PASS** | `api_compat.json` — 401/422/200, required fields, pagination |
| CONTENT_OUTPUT_REGRESSION | **PASS** | Golden fixtures + live `/content-ai/postprocess-content` + draft |
| KNOWN_FAILURES_NOT_INCREASED | **PASS** | 59 = 59 |

## Screenshot evidence (`docs/baseline/wave10/screenshots/`)

| File | What |
|------|------|
| desktop_content_ai.png | layout, header, sidebar, form |
| desktop_bulk_tab.png | bulk nav + table/upload |
| desktop_editor_typed.png | TinyMCE/visual editor + typed text |
| desktop_media_studio.png | upload/media studio |
| desktop_auth_modal_open.png | modal open |
| desktop_delete_modal.png | confirm modal |
| desktop_after_draft.png | form submit save |
| desktop_settings.png / pricing / account_billing | navigation |
| mobile_content_ai.png / mobile_nav_open.png | mobile + hamburger |
| tablet_content_ai.png | tablet |
| desktop_tool_logged_out.png | loading/empty tool shell |

## E2E actions (all ok)

open/close auth modal · mobile nav toggle · tab bulk/single · bulk table · editor input/save · TinyMCE controls · media studio · draft submit · delete modal · nav Settings · pricing · account-billing

## API compatibility (live)

- No/bad token → **401**
- Invalid draft → **422**
- `/auth/me` fields: `id, email, role, status, credit_balance`
- `/content-ai/projects?limit=5` paginated
- `/content-ai/usage`, `llm-providers`, `bulk-jobs/ping`, publishing-sites, audit, report → 200

## Content AI golden

- Same `ARTICLE_FIXTURES` as WAVE 0/1 (`test_content_ai_output_postprocess.py`)
- Live postprocess preserves `Nội dung SEO` / headings; no truncate
- Live `POST /content-ai/draft` returns `title, content, project_id, slug`

## HTML vs WAVE 0

`/content-ai` sha256 **identical**: `adf92ec76d4fd2743c3f0bfe3393183f6e7f43a968ea1c24242de93744b95f6e`  
No Jinja/JS/CSS product files changed in this wave.

## Run

```bash
cd /var/www/seoauto_vn_usr/data/www/seoauto.vn-current
PYTHONPATH=. .venv/bin/python scripts/wave10_ui_regression.py
```
