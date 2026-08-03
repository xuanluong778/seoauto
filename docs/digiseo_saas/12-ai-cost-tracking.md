# AI Cost Tracking

Tài liệu này mô tả hệ thống tracking chi phí AI cho Seoauto.

---

## 1. Vì sao cần tracking AI cost

Seoauto dùng AI nhiều:

```txt
Content AI
Bulk Content
Chatbot
Knowledge Base
AI Image
Keyword/SERP intelligence
```

Nếu dùng API Admin pool mà không tracking, app có thể bị lỗ.

---

## 2. Bảng ai_usage_logs

```txt
id
user_id
provider
model
feature
input_tokens
output_tokens
estimated_cost
status
error_message
created_at
```

---

## 3. Feature cần tracking

```txt
content_ai_article
content_ai_outline
content_ai_suggest
content_ai_bulk
chatbot_message
knowledge_base_search
image_generate
schema_generate
serp_intelligence
```

---

## 4. Admin cần xem được

```txt
Tổng chi phí AI hôm nay
Chi phí AI theo user
Chi phí AI theo module
User dùng nhiều nhất
Provider lỗi nhiều nhất
Model tốn tiền nhất
Tổng token input/output
```

---

## 5. Mục tiêu

```txt
Tránh lỗ khi user dùng quá nhiều API Admin pool
Biết tính năng nào tốn chi phí nhất
Tối ưu model phù hợp từng tác vụ
Cảnh báo user dùng bất thường
```

---

## 6. Cảnh báo nên có

```txt
User vượt ngưỡng AI cost/ngày
Provider lỗi liên tục
Model quá đắt so với tính năng
Bulk job tiêu thụ chi phí bất thường
```
