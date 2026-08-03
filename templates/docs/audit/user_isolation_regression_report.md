# User Data Isolation — Regression Audit Report

**Date:** 2026-06-25  
**Context:** Sau các sửa P0 security/billing (private uploads, JSON retention per-user, bulk charge, word_count policy).  
**Phương pháp:** Đọc code router/store + test tự động User A / User B. **Không sửa production code** trong prompt này.

---

## Executive summary

| Mức | Số lượng | Ghi chú |
|-----|----------|---------|
| **P0** (cross-user read/write) | **0** xác nhận | Các module chính đều filter `user_id` |
| **P1** | **1** | GSC checklist dùng file global legacy |
| **P2** | **3** | Keyword export không auth; admin gate chỉ email whitelist; legacy JSON còn sót |
| **PASS** | **Đa số endpoint** | Xem bảng chi tiết |

**Kết luận:** User A **không** đọc/sửa/xóa dữ liệu lưu trữ của User B trên các module đã kiểm tra (audit, Content AI projects, API keys, keyword history, publishing sites, private uploads, admin API). Rủi ro chính là **hiển thị số GSC chung** từ file global, không phải IDOR trực tiếp giữa hai user.

---

## Test đã chạy

```bash
cd /var/www/seoauto_vn_usr/data/www
pytest tests/test_user_data_isolation.py tests/test_p0_security_billing_fixes.py -q
```

**Kết quả:** `16 passed` (2026-06-25)

| Test | Module | Kết quả |
|------|--------|---------|
| `test_user_b_cannot_read_user_a_audit_api` | Technical audit | PASS |
| `test_user_b_mine_list_empty` | Technical audit list | PASS |
| `test_user_a_sees_own_audit` | Technical audit | PASS |
| `test_orphan_audit_not_visible_to_any_user` | Legacy orphan | PASS |
| `test_report_page_never_ssr_user_audit` | SSR `/report` | PASS |
| `test_content_ai_user_b_cannot_read_user_a_project` | Content AI JSON | PASS |
| `test_content_ai_retention_does_not_evict_other_users` | Retention | PASS |
| `test_user_b_cannot_read_user_a_cluster_history` | Keyword SQL | PASS |
| `test_user_b_cannot_read_user_a_api_key` | Settings API keys | PASS |
| `test_user_b_cannot_read_user_a_publishing_site` | Publishing sites JSON | PASS |
| `test_regular_user_cannot_call_admin_api_check` | Admin API | PASS |
| `test_user_a_cannot_read_user_b_private_upload` | `/api/user-files` | PASS |
| `test_audit_retention_does_not_evict_other_users` | Audit retention | PASS |
| (+ billing/word_count tests) | P0 billing | PASS |

---

## Primitives dùng chung

| File | Vai trò |
|------|---------|
| `app/services/user_scope.py` | `belongs_to_user`, `assert_job_access`, `require_owner_or_admin` |
| `app/services/json_atomic.py` | `mutate_json_list` + file lock + atomic write |
| `app/services/user_data_paths.py` | `data/users/{id}/` — notes, GSC, uploads |
| `app/services/rbac.py` | `require_admin_user` → `is_platform_admin()` |

**Quy tắc legacy:** Row thiếu `user_id` hoặc `legacy_orphan` → **không** trả cho user thường.

---

## 1. Content AI (projects / history / uploads)

### Endpoints user-facing (router `pages.py`, bulk routers)

| Endpoint | Auth | Filter | Status |
|----------|------|--------|--------|
| `GET /content-ai/projects` | `require_active_trial` | `list_content_ai_projects(user_id=current_user.id)` | **PASS** |
| `GET/DELETE /content-ai/projects/{id}` | ✓ | `get_content_ai_project(..., user_id=)` | **PASS** |
| `POST .../auto-insert-images`, thumbnails, export | ✓ | `user_id=current_user.id` | **PASS** |
| `GET /content-ai/bulk-jobs/{job_id}` | ✓ | `assert_job_access(payload, user_id)` | **PASS** |
| `POST /content-ai/upload-image` | ✓ | Private path `data/users/{id}/uploads/` | **PASS** |
| `GET /api/user-files/{owner_id}/...` | Bearer/cookie | `owner_id == current_user.id` or admin | **PASS** |

### JSON store: `data/content_ai_projects.json`

| Kiểm tra | Status |
|----------|--------|
| Filter `user_id` trước response | **PASS** — `_projects_for_user` + `belongs_to_user` |
| Retention per-user (max 120) | **PASS** — `_trim_retention_for_user` |
| Atomic write | **PASS** — `mutate_json_list` |
| Legacy orphan | **PASS** — `user_id=0`, `legacy_orphan=true`, hidden |

---

## 2. Technical audits / report

| Endpoint | Auth | Filter | Status |
|----------|------|--------|--------|
| `GET /api/audit/{id}`, `/mine`, `/latest`, `/runs` | ✓ | `get_audit_for_user(id, user_id)` | **PASS** |
| `DELETE /api/audit/{id}` | ✓ | Per-user delete | **PASS** |
| `POST /analyze/technical` | ✓ | Saves `user_id=current_user.id` | **PASS** |
| `GET/PUT /api/gsc-indexing-counts` | ✓ | `data/users/{id}/gsc_indexing_counts.json` | **PASS** |
| `GET /api/action-plan`, notes deploy | ✓ | Per-user notes/deploy files | **PASS** |
| `GET /api/report` | **Không** | Merge `data/gsc_indexing_counts.json` **global** | **FAIL (P1)** |
| `GET /report` (SSR) | Public | Không embed audit user | **PASS** |

### JSON: `data/technical_audits.json`

| Kiểm tra | Status |
|----------|--------|
| Filter user_id | **PASS** |
| Retention max 40/user | **PASS** (P0 fix) |
| `mutate_json_list` | **PASS** |

---

## 3. Keyword research / clustering

| Endpoint | Auth | Filter | Status |
|----------|------|--------|--------|
| `GET/DELETE /keywords/cluster/history*` | `get_current_user` | `user_id == current_user.id` | **PASS** |
| `GET/DELETE /keywords/research/history*` | ✓ | SQL `user_id` | **PASS** |
| `POST /keywords/research/run` | billing user | Saves `user_id` | **PASS** |
| `GET /keywords/research/task/{id}` | ✓ | `assert_task_owner` | **PASS** |
| `GET /keywords/cluster/job/{id}` | ✓ | `assert_job_access` | **PASS** |
| `POST /keywords/cluster`, `GET /research`, import | `get_billing_user` | Stateless khi credits off | **P2** (abuse, không IDOR) |
| `POST /keywords/export/*` | Không | Không đọc store user | **P2** (no auth) |

**DB:** `KeywordResearchProject`, `KeywordClusterProject` — cột `user_id`, filter trong router.

---

## 4. Index Control

Router: `/api/index-control/*` — tất cả `get_current_user`.  
Stores SQL: `IndexControlCheckItem.user_id`, admin-only `DELETE /history?user_id=`.

| Status |
|--------|
| **PASS** |

---

## 5. Google Map SEO / GBP

Router: `/api/google-map-seo/*` — ~49 route, `user.id` vào service layer.

| Status |
|--------|
| **PASS** |

---

## 6. Chatbot CSKH

| Area | Storage | Filter | Status |
|------|---------|--------|--------|
| Bots, inbox, KB, knowledge | SQL + `data/users/{id}/chatbot_cskh.json` | `_get_user_bot`, `user.id` | **PASS** |
| Public widget | `chatbot_cskh_public.py` | Rate limit + `bot_id`; không list cross-user | **PASS** |
| Facebook webhook | Unauthenticated | By design (verify signature) | N/A |

---

## 7. Billing / credit / subscription

| Endpoint | Filter | Status |
|----------|--------|--------|
| `/api/me`, `/api/billing-overview` | `current_user.id` | **PASS** |
| `/auth/credits/ledger`, `/transactions` | `CreditLedger.user_id == current_user.id` | **PASS** |
| `POST /api/credits/preview` | `get_current_user` | **PASS** |
| Sepay webhook | Server-only | N/A |

---

## 8. Settings / API keys

| Endpoint | Filter | Status |
|----------|--------|--------|
| `/api/settings/api-keys*` | `user_id=current_user.id` (SQL `user_api_keys`) | **PASS** |
| `/api/settings/publishing-sites*` | `belongs_to_user` JSON | **PASS** |
| `/api/settings/ai-knowledge-bases*` | `user_id` (+ `scope=global` admin) | **PASS** |
| `/api/settings/ai-provider`, `/system` | Nested `users.{id}` JSON | **PASS** |

---

## 9. Admin API

| Mount | Gate | User thường | Status |
|-------|------|-------------|--------|
| `/admin/api/*`, `/api/admin/*` | `require_admin_user` → `is_platform_admin()` | **403** | **PASS** |

**Lưu ý P2:** Admin API chỉ mở cho email trong `PLATFORM_ADMIN_EMAILS` (`admin_auth.py`), **không** dựa vào `role=admin` trong DB alone. Đây là hành vi có chủ đích nhưng dễ gây nhầm vận hành.

---

## 10. JSON global — tổng hợp

| File | Per-user? | Atomic/lock | Retention | Risk |
|------|-----------|-------------|-----------|------|
| `technical_audits.json` | ✓ | ✓ | Per-user 40 | Low |
| `content_ai_projects.json` | ✓ | ✓ | Per-user 120 | Low |
| `publishing_sites.json` | ✓ | Partial | — | Low |
| `ai_knowledge_bases.json` | ✓ | Partial | — | Low |
| `rank_tracking_*.json` | ✓ | — | — | Low |
| `social_auto_*.json` | ✓ | — | — | Low |
| `data/users/{id}/*` | ✓ | — | — | Low |
| **`gsc_indexing_counts.json`** | **✗ Global** | — | — | **P1** |
| `action_plan_notes.json` (legacy root) | Superseded | — | — | P2 cleanup |

---

## Findings — đề xuất patch riêng (không implement trong prompt này)

### P1-ISO-01 — GSC global overlay trong checklist

**Vấn đề:** `GET /api/report` và `build_seo_report_from_file()` đọc `data/gsc_indexing_counts.json` (global). API per-user GSC (`GET/PUT /api/gsc-indexing-counts`) ghi `data/users/{id}/gsc_indexing_counts.json`. User A cập nhật GSC có thể không khớp checklist; nếu global file chứa số liệu của một user, **mọi** caller thấy cùng số.

**Đề xuất patch:**
- `report_builder.apply_gsc_indexing_count_overrides` nhận `user_id` optional; ưu tiên per-user file.
- Deprecate/xóa ghi global; migrate one-time.

**Files:** `app/services/report_builder.py`, `app/routers/report.py`

---

### P2-ISO-01 — Keyword export không yêu cầu auth

**Vấn đề:** `POST /keywords/export/excel` v.v. không `get_current_user` — không leak data user khác (stateless) nhưng abuse compute.

**Đề xuất:** Thêm `get_billing_user` hoặc `get_current_user` tối thiểu.

---

### P2-ISO-02 — Admin gate chỉ whitelist email

**Vấn đề:** `role=admin` trong DB không đủ cho `/admin/api/*`.

**Đề xuất:** Document rõ hoặc align `require_admin_user` với `is_admin()` trong `rbac.py`.

---

### P2-ISO-03 — Legacy global JSON files

**Đề xuất:** Script migrate `action_plan_notes.json`, `gsc_indexing_counts.json` → per-user; xóa file root.

---

## Endpoint pass/fail matrix (tóm tắt)

| Module | Cross-user IDOR | Test |
|--------|-----------------|------|
| Technical audit API | PASS | ✓ |
| Content AI projects | PASS | ✓ |
| Private uploads | PASS | ✓ |
| Keyword cluster history | PASS | ✓ |
| API keys | PASS | ✓ |
| Publishing sites | PASS | ✓ |
| Admin API (user token) | PASS (403) | ✓ |
| Index Control | PASS (code review) | — |
| GBP / Google Map | PASS (code review) | — |
| Chatbot CSKH | PASS (code review) | — |
| Billing ledger | PASS (code review) | — |
| `GET /api/report` GSC overlay | **FAIL (P1)** | — |
| Keyword export no auth | P2 abuse | — |

---

## Việc tiếp theo (khuyến nghị)

1. Patch P1-ISO-01 (GSC per-user trong report builder).
2. Mở rộng test: Index Control history IDOR, chatbot inbox, GBP project — pattern giống keyword cluster.
3. Staging: manual pentest với 2 tài khoản thật trên từng module UI.

**Không deploy prod** chỉ dựa trên audit này nếu chưa fix P1-ISO-01 và chưa chạy test trên staging.
