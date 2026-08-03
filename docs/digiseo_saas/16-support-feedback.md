# Support & Feedback System

Tài liệu này mô tả hệ thống support và feedback cho Seoauto SaaS.

---

## 1. Vì sao cần support

Một SaaS chuyên nghiệp cần nơi để user:

```txt
Báo lỗi
Gửi góp ý
Hỏi về thanh toán
Yêu cầu hỗ trợ kỹ thuật
```

---

## 2. Route đề xuất

```txt
/support
/feedback
/help
```

---

## 3. Form support

```txt
Loại yêu cầu:
- Báo lỗi
- Góp ý tính năng
- Vấn đề thanh toán
- Cần hỗ trợ kỹ thuật

Tiêu đề
Nội dung
Ảnh đính kèm
Trang đang gặp lỗi
```

---

## 4. Database

```txt
support_tickets
ticket_messages
```

### support_tickets

```txt
id
user_id
type
title
status
priority
created_at
updated_at
```

### ticket_messages

```txt
id
ticket_id
sender_id
message
attachment_url
created_at
```

---

## 5. Admin cần có

```txt
Danh sách ticket
Lọc theo status
Xem chi tiết ticket
Trả lời ticket
Đổi trạng thái
Gắn priority
```

---

## 6. Giai đoạn đầu

Ban đầu có thể chưa cần inbox phức tạp.

Có thể làm đơn giản:

```txt
User gửi form
↓
Hệ thống gửi email về Gmail admin
↓
Admin xử lý thủ công
```
