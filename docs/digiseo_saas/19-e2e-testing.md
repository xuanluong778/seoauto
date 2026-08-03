# E2E Testing Roadmap

Tài liệu này mô tả các luồng cần test end-to-end cho Seoauto.

---

## 1. Vì sao cần E2E test

Pytest backend là tốt, nhưng SaaS cần test luồng người dùng thật.

E2E giúp tránh tình trạng:

```txt
Backend vẫn chạy
Nhưng UI bấm không được
```

---

## 2. Công cụ đề xuất

```txt
Playwright E2E
```

---

## 3. Luồng cần test

```txt
Đăng ký
Đăng nhập
Thêm API key
Tạo bài Content AI
Lưu bài viết
Kết nối WordPress
Đăng nháp WordPress
Chạy Technical Audit
Research keyword
Admin kích hoạt user
Admin bật API admin pool
Thanh toán thành công
```

---

## 4. Test nhóm Auth

```txt
User đăng ký
Nhận OTP
Xác thực OTP
Đăng nhập
Đăng xuất
Token hết hạn
```

---

## 5. Test nhóm Content AI

```txt
Tạo bài đơn
Tạo outline
Tạo nội dung
Lưu project
Mở lại project
Đăng WordPress nháp
Bulk import keyword
Start bulk job
Poll tiến độ
```

---

## 6. Test nhóm Admin

```txt
Admin đăng nhập
Xem danh sách user
Đổi status user
Bật API access
Bật API Admin pool
Cộng credit
Xem audit log
```

---

## 7. Test nhóm Billing

```txt
User xem pricing
Chọn gói
Tạo payment order
Webhook success
Subscription active
Quota cập nhật
```
