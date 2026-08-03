# Checklist QA — Pricing, Quota & Credit (SEOAuto)

Tài liệu kiểm thử thủ công + tự động cho billing hybrid (gói + quota + credit).

## Chạy test tự động

```bash
cd /var/www/seoauto_vn_usr/data/www
.venv/bin/python3 -m pytest tests/test_pricing_quota_credit_checklist.py -v
```

Bộ test liên quan (chạy thêm khi sửa billing):

```bash
.venv/bin/python3 -m pytest \
  tests/test_pricing_quota_credit_checklist.py \
  tests/test_cost_control.py \
  tests/test_content_ai_credit.py \
  tests/test_dataforseo_billing.py \
  tests/test_lead_scanner_cost.py \
  tests/test_payment_activation.py \
  tests/test_saas_economics.py \
  tests/test_billing_overview.py \
  tests/test_credit_preview.py \
  tests/test_chatbot_workflow_credit.py \
  -q
```

---

## Checklist theo yêu cầu

| # | Yêu cầu | Test auto | Pass |
|---|---------|-----------|------|
| 1 | User **thiếu credit** → không gọi API ngoài | `TestCheck01*` | ☐ |
| 2 | User **vượt quota** → không gọi API ngoài | `TestCheck02*` | ☐ |
| 3 | Mở trang / đổi tab / refresh UI **không gọi API đắt** | `TestCheck03*` | ☐ |
| 4 | Bấm nhiều lần → **1 request thật** (idempotency) | `TestCheck04*` | ☐ |
| 5 | **Cache** không phát sinh chi phí API / credit tối thiểu | `TestCheck05*` | ☐ |
| 6 | Lead Scanner **100 SĐT** → 1000–1200 credit | `TestCheck06*` | ☐ |
| 7 | Keyword Research **DataForSEO** trừ đúng credit | `TestCheck07*` | ☐ |
| 8 | **Content AI** trừ theo số từ (12/25/45) | `TestCheck08*` | ☐ |
| 9 | **Chatbot** vượt quota → trừ credit/reply | `TestCheck09*` | ☐ |
| 10 | **Admin** thấy cost theo module | `TestCheck10*` | ☐ |
| 11 | **SePay** kích hoạt đúng gói/credit | `test_payment_activation.py` | ☐ |
| 12 | Không ảnh hưởng tab khác | `TestCheck12*` + smoke thủ công | ☐ |

---

## Test thủ công chi tiết

### Chuẩn bị

- Tài khoản **A**: gói Pro, credit thấp (~20), quota gần hết.
- Tài khoản **B**: gói Starter (Basic), không có DataForSEO Live.
- Tài khoản **Admin**: vào `/admin/saas-economics`.
- Bật `CREDITS_ENABLED=1`, `COST_CONTROL_ENABLED=1` trên prod/staging.

---

### 1–2. Credit / quota chặn trước API

**Thiếu credit**

1. Đăng nhập user A (credit ~20).
2. Mở DevTools → Network, lọc `dataforseo`, `googleapis`, `openai`.
3. Chạy Keyword Research Live hoặc Lead Scanner 100 lead + lấy SĐT.
4. **Kỳ vọng**: popup «Không đủ credit» hoặc HTTP 402; **không** có request tới domain API ngoài.

**Vượt quota**

1. Dùng hết quota tháng (vd. `lead_scan` hoặc `keyword_research` trong tab Tổng quan billing).
2. Thử lại tác vụ cùng module.
3. **Kỳ vọng**: HTTP 429 / popup quota; không gọi API ngoài.

---

### 3. UI không gọi API đắt khi duyệt trang

1. `/account-billing` → tab **Tổng quan**, **Gói dịch vụ**, **Thanh toán**, **Affiliate**.
2. Hard refresh từng tab.
3. **Kỳ vọng** (Network): chỉ `/api/saas/*`, `/auth/*`, `/affiliate/*`, `/admin/api/*` (nếu admin); **không** DataForSEO/Google/OpenAI.

---

### 4. Double-click / bấm nhiều lần

1. Content AI: bấm «Gợi ý nội dung» 3 lần nhanh → chỉ 1 POST suggest thành công (nút disabled khi đang chạy).
2. Auto Update: publish cùng job → kiểm tra log không trừ credit 2 lần (idempotency key).
3. Lead «Lấy SĐT» trên cùng batch → không duplicate charge cho lead đã có `detail_fetched`.

---

### 5. Cache

1. Keyword Research: chạy cùng seed 2 lần → lần 2 popup ghi «Dữ liệu từ cache», credit thấp hơn hoặc 0.
2. Lead Scanner: quét lại cùng tham số trong TTL → credit = 0, không gọi Places API (xem `api_request_count` trong response admin nếu có).

---

### 6. Lead Scanner 100 SĐT

1. Gói Pro+, credit ≥ 1500.
2. Quét **100** lead (keyword), sau đó «Lấy SĐT» cho **100** lead.
3. **Kỳ vọng**: popup preview ~**1160** credit (5 trang scan × 12 + 100 × 11); sau khi xong, số dư giảm đúng; ledger module `lead_scanner`.

---

### 7. Keyword Research DataForSEO

| Gói | Mode | Credit (miss cache) |
|-----|------|---------------------|
| Starter | basic/cache | 5 |
| Pro+ | live | 30 |

Kiểm tra popup `DigiSeoConfirmCredit` trước khi chạy và ledger sau khi chạy.

---

### 8. Content AI theo số từ

| Độ dài | Credit base |
|--------|-------------|
| ~900 từ | 12 |
| ~1500 từ | 25 |
| ~2000 từ | 45 |

Bật addon (research, outline…) → tổng tăng đúng trong popup preview.

---

### 9. Chatbot CSKH vượt quota

1. Bot test, gói có `chatbot_reply` thấp.
2. Gửi tin đến khi hết quota tháng.
3. **Kỳ vọng**: reply tiếp vẫn hoạt động nếu đủ credit ví chung; trừ **2 credit**/reply (`reply_overage`); hết credit → chặn.

---

### 10. Admin economics

1. `/admin/saas-economics` (admin).
2. **Kỳ vọng**: burn theo module (`keyword`, `content_ai`, …), doanh thu SePay; **user thường không** thấy cost API nội bộ trên `/account-billing`.

---

### 11. SePay kích hoạt gói

1. Tạo đơn `STARTER_M` hoặc `CREDIT_100K` → chuyển khoản test / webhook SePay.
2. **Kỳ vọng**: `payment_orders.status=paid`, `activation_status=activated`, subscription/credit tăng; tab **Thanh toán** hiện đơn.

---

### 12. Regression các tab (smoke 5 phút/tab)

| Tab | Kiểm tra nhanh |
|-----|----------------|
| Technical Audit | Chạy audit 1 URL → kết quả OK, không 402 bất thường |
| Content AI | Gợi ý title, lưu bài |
| Keyword Research | Expand 1 seed |
| Index Control | Load overview |
| Google Map SEO | Mở lead scanner config |
| Chatbot CSKH | 1 tin nhắn test widget |

---

## File đã sửa (billing overview + guards)

| File | Vai trò |
|------|---------|
| `app/services/account_billing_overview_service.py` | API tổng hợp gói/credit/quota/history |
| `app/schemas/saas.py` | Schema `BillingOverviewResponse` |
| `app/routers/saas.py` | `GET /api/saas/billing-overview` |
| `templates/account_billing.html` | UI tab Tổng quan, thanh toán SePay |
| `static/js/account-billing.js` | Render dashboard, cache overview |
| `static/css/account-billing.css` | Style alerts, quota bars |
| `tests/test_billing_overview.py` | Test API billing overview |
| `tests/test_pricing_quota_credit_checklist.py` | **Regression checklist (mới)** |
| `tests/PRICING_QUOTA_CREDIT_CHECKLIST.md` | **Tài liệu này** |

### Billing / gate (đã có từ trước — regression khi sửa)

| File | Vai trò |
|------|---------|
| `app/services/cost_control/*` | Gate credit/quota trước API ngoài |
| `app/services/dataforseo_billing_service.py` | DataForSEO cache-first + credit |
| `app/services/content_ai_credit_service.py` | Content AI theo từ/addon |
| `app/services/credits.py` | Quote lead scanner, consume FIFO |
| `app/services/chatbot_cskh_credits.py` | Chatbot overage → ví credit |
| `app/services/payment_activation_service.py` | SePay → gói/credit |
| `app/services/saas_economics_service.py` | Admin burn/revenue |
| `static/js/digiseo-credit-confirm.js` | Popup xác nhận (chỉ `/api/credits/preview`) |
| `app/routers/credits_preview.py` | Preview nội bộ |

---

## Deploy prod (khi cần)

```bash
PROD=/var/www/seoauto_vn_usr4940/data/www/seoauto.vn
DEV=/var/www/seoauto_vn_usr/data/www
# copy file billing + tests doc nếu cần
bash "$PROD/scripts/restart_digiseo_safe.sh"
```

Sau deploy: hard refresh `/account-billing`, chạy lại checklist mục 3 và 11.
