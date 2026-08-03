# SEOAuto — Báo cáo rà soát toàn diện (Read-only)

| Thuộc tính | Giá trị |
|---|---|
| **Ngày rà soát** | 25/06/2026 |
| **Phạm vi** | Backend FastAPI (`/var/www/seoauto_vn_usr/data/www/`), templates, static, billing, Content AI, Chatbot CSKH |
| **Loại báo cáo** | Chỉ đọc & phân tích — **không sửa code, DB, billing, auth** |
| **Môi trường tham chiếu** | Dev (`seoauto_vn_usr`) + so sánh prod (`seoauto.vn`) |

> **Đường dẫn file:** `docs/audit/seoauto_full_audit_report.md` (project root: `/var/www/seoauto_vn_usr/data/www/`)

---

## Tóm tắt điều hành

Rà soát tập trung vào 6 trục: **user isolation**, **hiệu năng**, **Content AI/Chatbot**, **billing/credit/quota**, **UI/UX frontend**, **cấu trúc file quá lớn**.

| Mức độ | Số lỗi | Ý nghĩa |
|--------|--------|---------|
| **P0** | 7 | Rò rỉ dữ liệu, bypass billing, mất dữ liệu cross-user, blocking request |
| **P1** | 18 | Lộ token, quota sai, tải trang nặng, race condition billing |
| **P2** | 14 | N+1, cache kém, UX chậm, monolith khó bảo trì |
| **P3** | 8 | Tối ưu nhỏ, index DB, code smell |

**Đã khắc phục gần đây (không tính là lỗi mở):**
- SSR `/report` embed dữ liệu user khác qua cookie `seo_token` — đã fix (`report.py`, `report.html`, `audit_store.py`, user-scoped storage).
- Test isolation: `tests/test_user_data_isolation.py` (10 tests pass).

---

## Phương pháp rà soát

1. Đọc router/service/store liên quan auth, billing, audit, content-ai, chatbot.
2. Trace luồng `user_id` từ JWT → query DB/JSON → response/SSR.
3. Đo kích thước file, đếm route, kiểm tra static mount.
4. Review credit gate → charge → refund trên các workflow AI.
5. Không chạy penetration test thực tế; dựa trên static analysis + code path.

---

# P0 — Khẩn cấp (sửa ngay)

## P0-SEC-01: Upload media Content AI / GBP public không auth

| | |
|---|---|
| **File** | `app/routers/pages.py` (~dòng 486), `app/services/google_map_gbp_media_service.py` (~291), `main.py` (mount `/static`) |
| **Nguyên nhân** | File upload lưu dưới `/static/uploads/...` và được serve trực tiếp qua `StaticFiles` không qua middleware auth. URL có thể đoán hoặc lộ qua response API. |
| **Mức độ** | **Critical** — User A có thể truy cập ảnh/tài liệu của User B nếu biết URL |
| **Cách sửa đề xuất** | Serve upload qua endpoint có `get_current_user` + kiểm tra ownership; hoặc signed URL TTL ngắn; không mount thư mục user data dưới public static. |

---

## P0-SEC-02: JSON store global — retention xóa dữ liệu user khác

| | |
|---|---|
| **File** | `app/services/audit_store.py` (`MAX_RUNS=40`), `app/services/content_ai_project_store.py` (`MAX_PROJECTS=120`) |
| **Nguyên nhân** | Một file JSON chung cho mọi user; khi vượt cap, eviction FIFO/LRU theo toàn file → có thể xóa audit/project của user khác. |
| **Mức độ** | **Critical** — Mất dữ liệu + vi phạm isolation |
| **Cách sửa đề xuất** | Chuyển sang DB per-user (`user_id` FK) hoặc file shard `data/{user_id}/...`; retention theo `user_id`. |

---

## P0-BILL-01: Bulk Content AI bypass trừ credit

| | |
|---|---|
| **File** | `app/services/content_ai_bulk_runner.py`, `app/routers/pages.py` (bulk endpoints) |
| **Nguyên nhân** | Bulk runner chỉ gọi credit **gate** nhưng **không** gọi `charge_content_ai_write` / `record_content_ai_usage` sau khi ghi thành công. |
| **Mức độ** | **Critical** — Tạo hàng loạt bài AI miễn phí sau khi pass gate một lần |
| **Cách sửa đề xuất** | Trừ credit per article (idempotent theo `job_id` + `article_index`). |

---

## P0-PERF-01: Ghi/đọc JSON toàn file không lock (multi-worker)

| | |
|---|---|
| **File** | `audit_store.py`, `content_ai_project_store.py`, `cau_seo_fix_cache.py` |
| **Nguyên nhân** | `read → mutate → write` không file lock; multi-worker → lost update, corrupt JSON. |
| **Mức độ** | **High** |
| **Cách sửa đề xuất** | `fcntl.flock` / migrate DB; tối thiểu atomic write (`temp` + `os.replace`). |

---

## P0-PERF-02: Technical audit Playwright đồng bộ trong request HTTP

| | |
|---|---|
| **File** | `app/routers/analyze.py`, `app/services/playwright_crawler.py` |
| **Nguyên nhân** | Crawl block worker 30s–120s+. |
| **Mức độ** | **High** |
| **Cách sửa đề xuất** | Background job + polling/WebSocket; trả `job_id` ngay. |

---

## P0-PERF-03: SQLite + nhiều worker → database locked

| | |
|---|---|
| **File** | `app/database.py`, `main.py` |
| **Nguyên nhân** | SQLite write-heavy concurrent không phù hợp prod multi-worker. |
| **Mức độ** | **High** |
| **Cách sửa đề xuất** | PostgreSQL prod; hoặc `workers=1` + WAL tạm. |

---

## P0-BILL-02: `target_word_count` client-controlled cho billing tier

| | |
|---|---|
| **File** | `app/routers/pages.py`, content AI credit service |
| **Nguyên nhân** | Server tin count từ client để chọn tier thay vì đo output. |
| **Mức độ** | **High** |
| **Cách sửa đề xuất** | Tính tier từ output thực tế sau generate. |

---

# P1 — Cao (sprint tiếp theo)

## P1-SEC-01: JWT trong query string `/api/user-files?token=`

| **File** | `user_files.py`, `content-ai-state.js` | **Mức độ** | High |
| **Nguyên nhân** | Token lộ access log, Referer, history |
| **Cách sửa** | `Authorization: Bearer` hoặc signed one-time URL |

## P1-SEC-02: localStorage key global (keyword, seo_url_score)

| **File** | `seo-tool-page-init.js`, keyword scripts | **Mức độ** | Medium–High |
| **Cách sửa** | Prefix `seoauto:{uid}:` cho mọi module |

## P1-SEC-03: `seo_token` localStorage sau logout

| **File** | `digiseo-auth-token.js`, `digiseo-nav-auth.js` | **Cách sửa** | Clear on logout |

## P1-SEC-04: Facebook mock OAuth không session

| **File** | `chatbot_cskh_facebook.py` | **Cách sửa** | Signed state + tắt mock prod |

## P1-PERF-01: ~39 migration mỗi boot

| **File** | `main.py` | **Cách sửa** | Alembic version table |

## P1-PERF-02: Theme head ~14 CSS + 13 JS mọi trang

| **File** | `digiseo_theme_head.html` | **Cách sửa** | Split bundle theo route |

## P1-PERF-03: `/api/audit/latest` full payload, FE không dùng `lite=1`

| **File** | audit router, `report.html` | **Cách sửa** | Default lite |

## P1-PERF-04: `pages.py` 4944 dòng, 63+ routes

| **Cách sửa** | Tách content_ai, gbp, bulk routers |

## P1-PERF-05: Redis down → throttle silent fail

| **Cách sửa** | Fail closed hoặc in-memory + alert |

## P1-PERF-06: torch/sentence-transformers import lúc startup

| **Cách sửa** | Lazy import trong handler |

## P1-AI-01: Chatbot charge upfront, không refund khi fail

| **Cách sửa** | Reserve → commit / release |

## P1-AI-02: Race double-charge workflow đồng thời

| **Cách sửa** | `SELECT FOR UPDATE` credit balance |

## P1-AI-03: `suggest-stream` thiếu credit non-content fields

| **Cách sửa** | Unified `charge_content_ai_*` |

## P1-AI-04: Thiếu loading/abort — click nhiều lần

| **File** | `content-ai*.js`, chatbot JS | **Cách sửa** | Disable + AbortController |

## P1-AI-05: Word count stream lệch client/server

| **Cách sửa** | Server gửi `word_count` trong SSE final |

## P1-BILL-01: CSKH overage credits dead path

| **Cách sửa** | Reorder: plan → bonus → overage |

## P1-BILL-02: Payment activation partial commit

| **File** | `payment_activation_service.py` | **Cách sửa** | Single transaction |

## P1-BILL-03: Double quota enforce-word-count

| **Cách sửa** | Một điểm charge duy nhất |

## P1-BILL-04: Bulk quota model ≠ single write

| **Cách sửa** | `articles_count * tier_credits` |

## P1-OPS-01: `main.py` thiếu import `admin_saas_economics_router`

| **Mức độ** | High (dev boot fail) | **Cách sửa** | Thêm import hoặc comment router |

---

# P2 — Trung bình

| ID | Mô tả | File | Cách sửa |
|----|-------|------|----------|
| P2-PERF-01 | `report.html` ~812 dòng inline JS | `report.html` | Tách `report-dashboard.js` |
| P2-PERF-02 | `/content-ai` ~1.57MB JS | `content-ai*.js` | Dynamic import, code-split |
| P2-PERF-03 | CAU cache full R/W mỗi score | `cau_seo_fix_cache.py` | SQLite/Redis TTL |
| P2-PERF-04 | N+1 flush loop | `analyze.py` | Batch insert |
| P2-PERF-05 | Embedding COUNT lặp | keyword services | Aggregate query + cache |
| P2-UX-01 | Bulk job không progress | bulk UI | SSE progress |
| P2-UX-02 | Billing refresh chậm sau SePay | `account-billing.js` | Poll 2s × 30 |
| P2-UX-03 | Chatbot CSS mọi trang | `digiseo_theme_head.html` | Conditional load |
| P2-STRUCT-01 | `analyze.py` quá lớn | `analyze.py` | Tách job service |
| P2-STRUCT-02 | `main.py` quá lớn | `main.py` | `lifespan.py`, registry |
| P2-SEC-01 | Orphan audit rows trên disk | `audit_store.py` | Migration purge |
| P2-BILL-01 | Monthly bonus cần metric | `monthly_bonus_credit_service.py` | Admin alert |
| P2-AI-01 | Chatbot full history | CSKH service | Sliding window |
| P2-AI-02 | Content AI multi-tab race | `content-ai-state.js` | Optimistic lock `version` |

---

# P3 — Thấp

| ID | Mô tả | File | Cách sửa |
|----|-------|------|----------|
| P3-SEC-01 | Keyword no auth khi credits off | keyword routers | Luôn require auth |
| P3-PERF-01 | Thiếu composite DB index | migrations | `(user_id, created_at)` |
| P3-PERF-02 | Không gzip static | nginx | `gzip_static on` |
| P3-UX-01 | Admin table mobile overflow | `admin.html` | Kiểm tra cột plan/role |
| P3-UX-02 | Report thiếu skeleton | `report.html` | Placeholder cards |
| P3-OPS-01 | Dev/prod `main.py` drift | `main.py` | Env feature flags |
| P3-OPS-02 | Thiếu test bulk billing | `tests/` | `test_content_ai_bulk_charges_credits` |
| P3-STRUCT-01 | Credit logic trùng lặp | nhiều service | `CreditFacade` |

---

# Ma trận isolation

| Module | Backend `user_id` | FE scoped | Ghi chú |
|--------|-------------------|-----------|---------|
| `/report` | ✅ | ✅ | Đã fix SSR |
| Technical audit | ✅ | ⚠️ | Legacy localStorage |
| Content AI projects | ⚠️ | ⚠️ | P0-SEC-02 |
| Content AI uploads | ❌ | — | P0-SEC-01 |
| Keyword | ✅ | ⚠️ | P1-SEC-02 |
| Chatbot CSKH | ✅ | N/A | |
| Billing | ✅ | ✅ | SePay OK |
| Admin | ✅ | N/A | |
| GBP media | ⚠️ | — | P0-SEC-01 |

---

# File cần tách

| File | ~Dòng | Đề xuất |
|------|-------|---------|
| `pages.py` | 4944 | content_ai, gbp, bulk, media |
| `report.html` | 886 | JS riêng |
| `main.py` | lớn | lifespan, router_registry |
| `analyze.py` | lớn | audit_job_service |
| `content-ai*.js` | ~1.5MB | lazy routes |

---

# Billing đã ổn

- SePay webhook idempotency
- FIFO credit + row lock (ledger v3)
- Monthly bonus lock/unlock
- Account billing overview

---

# Lộ trình đề xuất (chưa thực hiện)

**Tuần 1 — P0:** Upload auth, JSON shard, bulk charge, Playwright async, word count server-side

**Tuần 2 — P1:** JWT query fix, localStorage namespace, chatbot reserve/commit, main.py import

**Tuần 3 — P1/P2:** Theme split, audit lite API, tách pages.py, Alembic

---

*Báo cáo read-only. Không thay đổi code, DB, billing, auth.*
