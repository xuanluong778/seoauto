# Content AI / Chatbot Write — Performance Report

**Date:** 2026-06-25  
**Scope:** Luồng viết content (single suggest, suggest-stream UI, bulk job, chatbot workflow). Không đổi billing/auth ngoài phạm vi charge/word_count đã có.

## Phương pháp đo

- Thêm `ContentAiWriteTimer` + log `content_ai_timing` / `content_ai_timing_summary` theo `request_id`.
- Smoke tests: `tests/test_content_ai_write_performance.py` + bộ word_count/credit hiện có.
- **Chưa deploy prod** — số liệu “sau” là ước lượng từ tối ưu code + micro-benchmark cache; cần đo trên staging với LLM thật để có số giây chính xác.

## 3 bước chậm nhất (trước tối ưu)

| # | Bước | Nguyên nhân | Ước lượng |
|---|------|-------------|-----------|
| 1 | **LLM generate + repair trùng** | Stream không enforce server; client luôn gọi `/enforce-word-count` (thêm 1 LLM). Bulk/chatbot có thể repair khi lệch >15%. | 15–90s tùy model |
| 2 | **Fetch website context** | `_fetch_source_text` + WP REST tuần tự, timeout 18s mỗi call, không cache trong request. Outline + content gọi lại. | 2–36s (worst) |
| 3 | **JSON project store** | `save_or_update` / `update` đọc + ghi toàn bộ `content_ai_projects.json`; migration legacy mỗi lần read. | 50–500ms+ (file lớn) |

## Tối ưu đã áp dụng

### 1. LLM — tránh gọi thừa
- Server repair/trim chỉ khi lệch **> ±15%** (policy có sẵn).
- Response thêm `skip_client_enforce` khi trong band ±15%.
- UI skip `enforceWordCountAfterWrite` khi `skip_client_enforce` / `word_count_ok` hoặc đếm từ local trong ±15%.

### 2. Website / research cache
- `content_ai_request_cache.py` — cache theo request/job.
- `_fetch_website_context_bundle()` — fetch homepage + related posts **song song**, cache key theo site+keyword.
- Knowledge base `get_relevant_knowledge_for_keyword` cache trong cùng request.
- HTTP timeout website: 18s → **10s**.

### 3. JSON store
- `update_content_ai_project_fields`, `delete`, `save_content_ai_project`, `save_or_update_written_bulk_project` dùng `mutate_json_list` (lock + atomic write, **một lần ghi**).
- Legacy migration chỉ chạy khi còn orphan, không rewrite mỗi read.

### 4. Chatbot images — không block response
- `CONTENT_AI_CHATBOT_DEFER_IMAGES=1` (default): ảnh chạy **background thread**, step UI “Đang xử lý ảnh nền”.
- `stats.images_deferred=true` khi defer.

### 5. Timing & UI progress
- Log steps: `validate_input`, `check_plan_credit`, `fetch_website_context`, `research`, `outline`, `llm_generate`, `word_count_check`, `repair_word_count`, `process_images`, `save_project`, `return_response`.
- Editor write bar: Kiểm tra yêu cầu → Viết nội dung → Kiểm tra số từ → Tối ưu SEO → Hoàn thành.

## Endpoint — ước lượng trước / sau

| Endpoint / luồng | Trước (ước lượng) | Sau (ước lượng) | Ghi chú |
|------------------|-------------------|-----------------|---------|
| `POST /content-ai/suggest` (content) | 25–120s | 20–75s | Bỏ client enforce thừa; cache context |
| `POST /content-ai/suggest-stream` + UI | 30–130s | 22–85s | Skip enforce ±15%; progress rõ hơn |
| Bulk `_write_one_article` | 40–150s/bài | 35–120s/bài | Cache context outline+content; mutate JSON |
| Chatbot `write_article` + images | 45–180s | 25–100s phản hồi UI | ảnh defer ~5–30s không chặn |

*Chênh lệch lớn nhất khi có `target_website` + bật ảnh chatbot.*

## File đã sửa

| File | Thay đổi |
|------|-----------|
| `app/services/content_ai_write_timing.py` | **Mới** — timer + `mark_step` |
| `app/services/content_ai_request_cache.py` | **Mới** — cache request-scoped |
| `app/services/llm_content_writer.py` | Bundle fetch song song + cache + timing marks |
| `app/services/content_ai_project_store.py` | `mutate_json_list`, migration có điều kiện |
| `app/services/content_ai_word_count_policy.py` | `skip_client_enforce` |
| `app/routers/pages.py` | Timing `/content-ai/suggest` |
| `app/services/content_ai_bulk_runner.py` | Cache + timer per article |
| `app/services/chatbot_workflow_runner.py` | Defer images + timing |
| `static/js/content_ai/content-ai-editor.js` | Progress steps + skip enforce |
| `tests/test_content_ai_write_performance.py` | **Mới** — smoke perf |

## Smoke test

```bash
cd /var/www/seoauto_vn_usr/data/www
pytest tests/test_content_ai_write_performance.py \
  tests/test_content_ai_word_count_flow.py \
  tests/test_p0_security_billing_fixes.py -q
```

**Kết quả (2026-06-25):** `19 passed` — cache, skip_client_enforce, timing, mutate JSON store, word_count + credit regression.

## Việc tiếp theo (staging)

1. Đo log `content_ai_timing_summary` 20 request thật → cập nhật bảng giây chính xác.
2. suggest-stream: buffer cuối stream để enforce server-side (bỏ hẳn client enforce).
3. Migrate `content_ai_projects.json` → DB per-user để bỏ read full file khi list.
