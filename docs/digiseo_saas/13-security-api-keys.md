# Security & API Key Management

Tài liệu này mô tả nguyên tắc bảo mật API key trong Seoauto.

---

## 1. Hiện trạng

Hệ thống đã có:

```txt
Mã hóa API key user bằng cryptography
Admin API pool qua env.local
Bật/tắt API access theo user
Bật/tắt dùng API Admin pool
```

Đây là nền tảng tốt.

---

## 2. Nguyên tắc bắt buộc

```txt
Không bao giờ hiển thị lại full API key
Chỉ hiển thị dạng sk-****abcd
Có nút test key
Có nút xóa key
Có audit log khi thêm/sửa/xóa key
Không log API key ra terminal
Không đưa key vào response frontend
Service role key không nằm trong code
```

---

## 3. Audit log nên ghi

```txt
user_login
api_key_created
api_key_deleted
wordpress_connected
admin_changed_user_status
admin_granted_credit
payment_success
payment_failed
subscription_changed
```

---

## 4. UI API key nên có

```txt
Tên provider
Trạng thái key
Ngày thêm
Nút test
Nút xóa
Chỉ hiển thị 4 ký tự cuối
Không có nút xem full key
```

---

## 5. Admin cần thấy

```txt
User có key hay không
Provider nào đang dùng
Key có active không
Lần test key gần nhất
Không được thấy full key của user
```

---

## 6. Cảnh báo bảo mật

```txt
Không commit env.local
Không upload API key lên ChatGPT/Cursor
Không log request chứa API key
Không để SECRET_KEY mặc định trong production
```
