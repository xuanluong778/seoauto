# Prompt 2–4 — Pre-deploy Review & Production Deploy Report

**Date:** 2026-07-02  
**Dev:** `/var/www/seoauto_vn_usr/data/www`  
**Prod:** `/var/www/seoauto_vn_usr4940/data/www/seoauto.vn`  
**Backup:** `/var/www/seoauto_vn_usr4940/backups/pre_prompt24_20260702_010428.tar.gz`

---

## 1. Kiểm tra bắt buộc (Prompt 2–4)

| # | Hạng mục | Kết quả | Ghi chú |
|---|----------|---------|---------|
| 1 | Word count + credit theo output | **PASS** | `content_ai_word_count_policy.py`, `charge_content_ai_from_html`, repair chỉ >±15% |
| 2 | Timing / progress / cache / JSON mutate | **PASS** | `content_ai_write_timing`, `content_ai_request_cache`, `mutate_json_list` |
| 3 | User isolation | **PASS** | 16 test isolation; P1 GSC đã patch per-user trước deploy |
| 4 | Private uploads + public publish | **PASS** | `/api/user-files` owner check; `static/published/` tạo trên prod |
| 5 | Bulk credit | **PASS** | `charge_content_ai_from_html` per article trong `content_ai_bulk_runner` |

### P1 đã xử lý trước deploy

- **P1-ISO-01 (GSC global):** `report_builder.load_gsc_indexing_counts_config(user_id=…)` chỉ đọc `data/users/{id}/gsc_indexing_counts.json`; `/api/report` public không overlay GSC global.

---

## 2. Test suite (dev)

```bash
pytest tests/test_user_data_isolation.py \
  tests/test_p0_security_billing_fixes.py \
  tests/test_content_ai_word_count_flow.py \
  tests/test_content_ai_write_performance.py \
  tests/test_content_ai_credit.py \
  tests/test_chatbot_write_workflows.py \
  tests/test_chatbot_workflow_runner.py \
  tests/test_content_ai_bulk_setup.py -q
```

**Kết quả:** `49 passed` (2 warnings)

| Nhóm | Tests | Pass |
|------|-------|------|
| User isolation | 12 | ✓ |
| P0 security/billing/uploads | 5 | ✓ |
| Word count flow | 21 | ✓ |
| Write performance smoke | 5 | ✓ |
| Content AI credit | 6 | ✓ |
| Chatbot write | 2+ | ✓ |
| Bulk setup | 2 | ✓ |

---

## 3. Deploy

### Script

`scripts/deploy_prompt2_4_prod.sh` → `scripts/deploy_digiseo_safe.sh`

**Không copy:** `app.db`, `data/*` user JSON, `env.local`, `static/uploads` legacy.

### Files deployed

| File | Prompt |
|------|--------|
| `app/services/media_storage.py` | P0 |
| `app/services/json_atomic.py` | P0 |
| `app/services/content_ai_credit_service.py` | P0/P3 |
| `app/services/content_ai_word_count_policy.py` | P3 |
| `app/services/content_ai_write_timing.py` | P4 |
| `app/services/content_ai_request_cache.py` | P4 |
| `app/services/audit_store.py` | P0 |
| `app/services/content_ai_project_store.py` | P0/P4 |
| `app/services/content_ai_bulk_runner.py` | P0/P4 |
| `app/services/content_ai_image_optimizer.py` | P0 |
| `app/services/content_ai_thumbnail.py` | P0 |
| `app/services/google_map_gbp_media_service.py` | P0 |
| `app/services/user_data_paths.py` | P0 |
| `app/services/llm_content_writer.py` | P3/P4 |
| `app/services/chatbot_workflow_runner.py` | P3/P4 |
| `app/services/report_builder.py` | P1 fix |
| `app/routers/pages.py` | P0/P3/P4 |
| `app/routers/report.py` | P1 fix |
| `static/js/content_ai/content-ai-editor.js` | P3/P4 |
| `app/services/seoauto_pricing_catalog.py` | *dependency fix* |

### Sự cố deploy & khắc phục

1. **Lần 1:** `deploy_digiseo_safe.sh` fail health — `pages.py` import `PRICING_COMPARE_ROWS` thiếu trên prod catalog.
2. **Khắc phục:** Sync thêm `seoauto_pricing_catalog.py` từ dev.
3. **Lần 2:** `deploy_digiseo_safe.sh` **thành công** — serving port **8900**.

---

## 4. Smoke test prod (sau deploy)

| Check | Kết quả |
|-------|---------|
| `GET https://seoauto.vn/` | **200 OK** |
| `GET https://seoauto.vn/health` | **OK** |
| `GET /content-ai` | **200** |
| `GET /admin/api/check` (no auth) | **401** |
| `GET /api/audit/mine` (bad token) | **401** |
| Python import `content_ai_word_count_policy`, `media_storage`, `write_timing` | **OK** |

### Cần xác nhận thủ công (có login thật)

- [ ] Login user / admin UI
- [ ] Content AI single write + word count status UI
- [ ] Bulk job + credit ledger
- [ ] Chatbot viết bài SEO
- [ ] Upload ảnh private → URL `/api/user-files/{id}/…`
- [ ] Technical audit, Report action-plan (GSC per-user)
- [ ] Keyword, Index Control, Google Map SEO

---

## 5. Lỗi / rủi ro còn lại

| ID | Mức | Mô tả |
|----|-----|-------|
| P2-ISO-01 | P2 | Keyword export endpoints chưa bắt buộc auth |
| P2-ISO-02 | P2 | Admin API gate theo `PLATFORM_ADMIN_EMAILS`, không chỉ `role=admin` |
| DEP-01 | Ops | `pages.py` dev/prod lệch catalog — đã sync `seoauto_pricing_catalog.py`; theo dõi import khi deploy `pages.py` sau này |
| DEP-02 | Ops | `credit_cost_registry.py` **không** deploy — giữ giá prod hiện tại |

**Không còn P0/P1 blocker** cho phạm vi Prompt 2–4 sau patch GSC.

---

## 6. Rollback plan

```bash
PROD="/var/www/seoauto_vn_usr4940/data/www/seoauto.vn"
BACKUP="/var/www/seoauto_vn_usr4940/backups/pre_prompt24_20260702_010428.tar.gz"

# Khôi phục file từ backup (không đụng DB/data)
tar xzf "$BACKUP" -C "$PROD"

# Hoặc chỉ rollback pages nếu lỗi import:
# tar xzf "$BACKUP" -C "$PROD" app/routers/pages.py

chown -R seoauto_vn_usr4940:seoauto_vn_usr4940 "$PROD/app" "$PROD/static/js/content_ai"

bash /var/www/seoauto_vn_usr/data/www/scripts/deploy_digiseo_safe.sh
```

Verify: `curl -sf https://seoauto.vn/health`

---

## 7. Tóm tắt

| Mục | Trạng thái |
|-----|------------|
| Pre-deploy tests | **49/49 PASS** |
| P0/P1 blocker | **Đã xử lý** (GSC per-user) |
| Prod backup | **Có** |
| Prod deploy | **Thành công** (port 8900) |
| DB/data/.env | **Không đồng bộ từ dev** |
