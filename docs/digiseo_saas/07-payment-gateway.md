# Payment Gateway Roadmap

Tài liệu này mô tả định hướng tích hợp payment gateway cho Seoauto SaaS.

---

## 1. Mục tiêu

Seoauto cần hệ thống thanh toán thật để tự động kích hoạt gói dịch vụ.

---

## 2. Cổng thanh toán đề xuất

Với thị trường Việt Nam, nên ưu tiên:

```txt
PayOS
VNPay
Momo
Chuyển khoản QR tự động
```

Khuyến nghị bắt đầu:

```txt
PayOS + QR chuyển khoản tự động
```

---

## 3. Luồng thanh toán

```txt
User chọn gói
↓
Tạo payment order
↓
Hiển thị QR thanh toán
↓
User thanh toán
↓
Payment gateway gọi webhook
↓
Xác thực webhook
↓
Ghi payment_transactions
↓
Kích hoạt subscription
↓
Cộng quota/credits
↓
Ghi audit log
```

---

## 4. Bảng payment_transactions

```txt
id
user_id
subscription_id
plan_id
provider
provider_order_id
amount
currency
status
raw_payload
created_at
updated_at
```

Status:

```txt
pending
paid
failed
cancelled
refunded
```

---

## 5. Nguyên tắc an toàn

```txt
Không kích hoạt gói nếu webhook chưa xác thực
Không tin dữ liệu từ frontend
Không lưu thông tin thẻ/thông tin nhạy cảm
Payment lỗi thì user giữ trạng thái cũ
Mọi thay đổi gói phải có audit log
Webhook phải chống gọi lại trùng
```

---

## 6. Trang cần có

```txt
/pricing
/billing
/billing/success
/billing/cancel
/admin/payments
```

---

## 7. Admin cần quản lý

```txt
Danh sách giao dịch
Trạng thái thanh toán
User đã mua gói nào
Lỗi webhook
Kích hoạt thủ công nếu cần
Lịch sử nâng/hạ gói
```
