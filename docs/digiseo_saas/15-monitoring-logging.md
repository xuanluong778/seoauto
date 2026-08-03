# Monitoring & Logging

Tài liệu này mô tả hệ thống monitoring và logging cần có cho Seoauto SaaS.

---

## 1. Vì sao cần monitoring

Khi user trả tiền, cần biết:

```txt
App có đang sống không?
API nào đang lỗi?
User nào gặp lỗi?
AI provider nào lỗi?
Payment webhook có lỗi không?
Background job có treo không?
```

---

## 2. Nên có

```txt
Error logging
Request logging
AI cost logging
Payment logging
Background job logging
Uptime monitoring
```

---

## 3. Công cụ gợi ý

```txt
Sentry
Better Stack
Logtail
Grafana
UptimeRobot
```

Tối thiểu nên có:

```txt
Sentry cho backend FastAPI
UptimeRobot kiểm tra website sống/chết
Log file riêng cho production
```

---

## 4. Log quan trọng

```txt
auth_error
payment_webhook_error
ai_provider_error
wordpress_publish_error
technical_audit_error
bulk_job_error
database_error
permission_error
```

---

## 5. Admin cần xem

```txt
Lỗi mới nhất
Lỗi theo user
Lỗi theo module
Payment failed
AI provider failed
Background job failed
```

---

## 6. Nguyên tắc

```txt
Không log API key
Không log password
Không log token nhạy cảm
Log phải đủ thông tin để debug
Log lỗi phải có user_id nếu có
```
