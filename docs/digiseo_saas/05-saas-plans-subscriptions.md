# SaaS Plans & Subscriptions

Tài liệu này mô tả hệ thống gói dịch vụ và subscription cho Seoauto SaaS.

---

## 1. Mục tiêu

Seoauto cần có gói dịch vụ rõ ràng để bán SaaS chuyên nghiệp.

Hệ thống cần trả lời được:

```txt
User đang dùng gói gì?
Gói còn hạn không?
User được dùng bao nhiêu quota?
Khi hết quota thì xử lý thế nào?
Admin có thể nâng/hạ gói thủ công không?
```

---

## 2. Gói đề xuất

## Free Trial

```txt
Dùng thử 7 ngày
3 bài Content AI
3 lần Technical Audit
50 keyword research
Không bulk content
Không publish hàng loạt
Không white-label report
```

## Starter

```txt
199.000đ/tháng
30 bài Content AI/tháng
30 lần Technical Audit/tháng
1 website WordPress
500 keyword research/tháng
Schema tool
PDF report cơ bản
```

## Pro

```txt
499.000đ/tháng
150 bài Content AI/tháng
100 lần Technical Audit/tháng
5 website WordPress
5.000 keyword research/tháng
Bulk content
Internal link tự động
Google Sheet export
Content score
```

## Agency

```txt
1.499.000đ/tháng
Nhiều website
Nhiều client
Bulk content nâng cao
White-label report
API riêng
Team member
Hỗ trợ ưu tiên
```

---

## 3. Database cần thêm

```txt
plans
subscriptions
usage_limits
usage_events
monthly_usage
payment_transactions
```

---

## 4. Bảng plans

```txt
id
name
slug
price
billing_cycle
description
is_active
created_at
updated_at
```

Ví dụ slug:

```txt
free_trial
starter
pro
agency
```

---

## 5. Bảng subscriptions

```txt
id
user_id
plan_id
status
started_at
current_period_start
current_period_end
cancel_at_period_end
created_at
updated_at
```

Status:

```txt
trialing
active
past_due
cancelled
expired
```

---

## 6. Bảng usage_limits

```txt
id
plan_id
feature_key
limit_value
period
created_at
updated_at
```

Ví dụ feature_key:

```txt
content_ai_article
technical_audit
keyword_research
wordpress_site
bulk_content
```

---

## 7. Nguyên tắc migration

```txt
Không xóa logic trial/credits hiện tại ngay
Tạo lớp service mới để kiểm tra entitlement/quota
Cho hệ thống cũ và hệ thống mới chạy song song một thời gian
Admin có thể xem cả credit cũ và subscription mới
```
