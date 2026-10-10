# WAVE 10 — issues log

## Product UI / Content AI

**None.** HTML SHA256 of all 16 WAVE 0 pages matches current production. No UI, business logic, Content AI output, or Facebook App Review changes.

## Harness false positives (not product bugs)

1. **authModal on `/content-ai`** — modal lives in `/tool` + home partials, not Content AI template. WAVE 0 HTML already lacked that id (byte-identical).
2. **Tablet `#digiseoNavMenu` bbox null** — hamburger collapse at 768px (same as mobile). Expected responsive, not a layout regression.
3. **`a[href=/settings]` click timeout** — leftover overlay after modal probe. Navigation via force-click / `goto` still landed on `/settings`.
4. **`test_report_api_requires_auth` 401** — WAVE 8 `JWT_BLOCK_LEGACY_USER` rejects fixture `create_access_token` without `sid/jti`. Not Content AI output. Excluded from CONTENT_OUTPUT pytest filter (`-k not test_report_api_requires_auth`). Live `/api/report` with service token returns 200.

## Fixes applied

Only WAVE 10 test harness (`scripts/wave10_ui_regression.py`). No product UI files.
