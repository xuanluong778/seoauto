# Technical Analysis — Manual QA Checklist

Sau nâng cấp normalized output / GSC hybrid. Chạy trên `/tool` (class `seo-tool-page`).

**Chuẩn bị:** DevTools → Console (lọc Error/Warning), Network. JWT đăng nhập hợp lệ.

## 1. Kịch bản quét

| # | Kịch bản | Cách tạo | Kỳ vọng |
|---|----------|----------|---------|
| 1.1 | Crawl-only | Tắt GSC / không tick «Dùng GSC» | `scan_mode` = crawl_only; GSC Intel ẩn; disclaimer crawl-only |
| 1.2 | Hybrid GSC | GSC đã kết nối, tick GSC, property hợp lệ | Overview có GSC stats; issue có badge GSC/hybrid |
| 1.3 | GSC chưa kết nối | User chưa OAuth GSC | Quét vẫn xong; không crash; crawl issues hiển thị |
| 1.4 | GSC token lỗi | Revoke token / hết hạn trong Settings | `partial_data` hoặc message lỗi; crawl vẫn có kết quả |
| 1.5 | GSC quota exceeded | `url_inspection_limit` cao hoặc property lớn | Disclaimer quota; partial GSC; không crash |
| 1.6 | Không có critical | Site sạch / chỉ low-medium | Score grid: Critical = 0; không badge đỏ critical |
| 1.7 | Nhiều issue | Site lớn hoặc staging lỗi | Card view + filter; sidebar badge; search hoạt động |
| 1.8 | Audit cũ | Mở từ «Lần quét gần đây» (trước upgrade) | Overview fallback từ `issues`; sidebar từ legacy grouping |

## 2. Responsive

| Viewport | Kiểm tra |
|----------|----------|
| **375px** (mobile) | Sidebar → chips ngang; Card view (không Table); Passed Checks collapse; không scroll ngang |
| **768px** (tablet) | 2 cột score/issues; sidebar có thể thu gọn |
| **1366px** (desktop) | Sidebar 250px + main; Table view toggle hiện; filter chips đầy đủ |

## 3. Console JS

- [ ] Không có `Uncaught` / `ReferenceError` sau load trang
- [ ] Không lỗi khi `openAuditRun`, sau POST `/analyze/technical`
- [ ] Không lỗi khi resize 375 → 1366
- [ ] Không lỗi khi filter/search/export click

## 4. Nút & tương tác

### Issue cards
- [ ] **Xem URL** — mở panel danh sách URL; disabled khi không có URL
- [ ] **Hướng dẫn sửa** — hiện `how_to_fix` hoặc GROUP_SOLUTIONS_VI
- [ ] **Copy prompt sửa lỗi** — clipboard có nội dung; toast/feedback (nếu có)

### Filter & search
- [ ] Chips: All, Critical, High, Medium, Low, Passed, GSC/Crawl/Hybrid, Has URLs
- [ ] Search box lọc theo title/description/URL
- [ ] Đổi filter không làm crash khi audit cũ (không có `normalized_issues`)

### Sidebar category
- [ ] Click nav → scroll/filter đúng section
- [ ] Badge số từ `category_summaries` (mới) hoặc legacy `issues` (cũ)
- [ ] Mobile category chips đồng bộ với sidebar

### Export (cần `audit_id` sau quét)
- [ ] **CSV** — `GET /api/audit/{id}/export.csv` — UTF-8 BOM, có cột tiếng Việt
- [ ] **PDF** — `GET /api/audit/{id}/export.pdf` — tải được, có severity + message
- [ ] **Google Sheet (TSV)** — `GET /api/audit/{id}/export.gsheet` — tab-separated

### Khác
- [ ] **Lần quét gần đây** — list + mở lại audit
- [ ] **Passed Checks** — hiện khi có `passed_checks`; ẩn khi audit cũ trống

## 5. Regression — không được phá

| Hạng mục | Kiểm tra |
|----------|----------|
| Đăng nhập JWT | Login → token → `/tool` load |
| Google OAuth | Settings connect GSC (không đổi flow) |
| `POST /analyze/technical` | 200 + `audit_id` + legacy `issues` vẫn có |
| `GET /api/audit/*` | latest, mine, `{id}`, export.* |
| Report page `/report` | Vẫn render với `latest_audit` |

## 6. Kết quả automated QA (backend)

Chạy:

```bash
cd data/www && .venv/bin/pytest \
  tests/test_technical_analysis_qa.py \
  tests/test_technical_audit_routes.py \
  tests/test_audit_compat_export.py \
  tests/test_technical_output_normalizer.py -q
```

**Phạm vi đã cover (45 tests):**

| Nhóm | Tests |
|------|-------|
| `normalize_crawl_issues` | suppressed skip, field mapping |
| `normalize_gsc_issues` | confirmed, inspection FAIL, partial/quota, disabled |
| `merge_duplicate_issues` | URL merge, hybrid upgrade |
| `calculate_technical_health_score` | critical penalty, partial GSC discount |
| `build_top_priority_fixes` | ranking by priority_score |
| `build_passed_checks` / `build_category_summaries` | counts, worst severity |
| GSC fallback | crawl_only, token/quota/permission payloads |
| Audit cũ | `normalize_audit_record`, export fallback, file store |
| API routes | GET audit, mine, CSV/PDF/GSheet export |

## 7. Rà soát code (static)

| Mục | Kết quả |
|-----|---------|
| `normalizeAuditPayload` | Gọi trước render — audit cũ không crash |
| GSC null | `renderGscIntelligenceSummary` + `resolveGscIntelligenceSummary` ẩn section |
| Export | `resolve_audit_issues_for_export` → normalized ưu tiên |
| JS handlers | Issue buttons delegate trên `#issuesCardsView`; `cachedIssuesById` index theo `id` |
| Regression API | Route tests không đụng OAuth; JWT qua `create_access_token` |

**Lưu ý UX:** Nút «Xem URL» vừa toggle panel vừa `window.open` URL đầu tiên — kiểm tra thủ công có đúng ý product không.

## 8. Ghi nhận lỗi

```
Ngày:
Người test:
Trình duyệt / viewport:
Kịch bản:
Steps:
Expected:
Actual:
Console:
Network (status):
Screenshot:
```
