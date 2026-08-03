# Credits & Usage Limits

Tài liệu này mô tả cách chuẩn hóa credit và giới hạn sử dụng cho Seoauto SaaS.

---

## 1. Mục tiêu

Mỗi hành động quan trọng trong app cần được ghi nhận và giới hạn.

Cần biết:

```txt
User dùng tính năng gì?
Dùng bao nhiêu lần?
Tốn bao nhiêu credit?
Có vượt quota không?
Tính năng nào tốn chi phí AI nhất?
```

---

## 2. Các event nên tracking

```txt
technical_audit
seo_score
content_ai_article
content_ai_bulk_article
keyword_research
keyword_cluster
schema_generate
wp_publish
image_generate
chatbot_message
knowledge_base_search
```

---

## 3. Ví dụ credit

```txt
Tạo 1 bài SEO: 5 credits
Tạo 1 ảnh AI: 10 credits
Quét technical 1 domain nhỏ: 3 credits
Research 100 keyword: 5 credits
Gom nhóm keyword: 5 credits
Đăng WordPress: 1 credit
```

---

## 4. Bảng usage_events

```txt
id
user_id
event_type
credits_used
feature
metadata
created_at
```

---

## 5. Bảng monthly_usage

```txt
id
user_id
plan_id
month
content_articles_used
technical_audits_used
keyword_research_used
credits_used
created_at
updated_at
```

---

## 6. Nguyên tắc xử lý khi hết quota

```txt
Không cho chạy tính năng tốn phí
Hiển thị thông báo rõ ràng
Gợi ý nâng cấp gói
Không trừ credit nếu tác vụ thất bại trước khi gọi AI/API
Có rollback nếu payment hoặc job lỗi
```

---

## 7. Admin cần xem được

```txt
User nào dùng nhiều nhất
Tính năng nào dùng nhiều nhất
Tổng credit đã dùng
Tổng credit còn lại
Credit theo ngày/tháng
Credit theo module
```
