# Cursor Prompt - Payment Gateway

Dùng prompt này trong Cursor sau khi đã có Plan / Subscription / Usage Limit.

---

```txt
Tôi muốn tích hợp payment gateway cho Seoauto SaaS.

Bối cảnh:
- App dùng FastAPI + SQLAlchemy + Jinja2
- Đã có plans, subscriptions, usage_events, payment_transactions
- Thị trường chính là Việt Nam
- Tôi muốn ưu tiên PayOS hoặc cổng thanh toán có QR chuyển khoản tự động

Yêu cầu:
1. Đề xuất kiến trúc payment an toàn.
2. Tạo luồng:
   - User chọn gói
   - Tạo payment order
   - Hiển thị QR thanh toán
   - Nhận webhook từ payment gateway
   - Xác thực webhook
   - Cập nhật payment_transactions
   - Kích hoạt subscription
   - Ghi audit log
3. Không kích hoạt gói nếu webhook chưa xác thực.
4. Không lưu thông tin nhạy cảm không cần thiết.
5. Tạo trang pricing và trang billing.
6. Admin xem được danh sách payment.
7. Viết hướng dẫn test sandbox.

Lưu ý:
- Không làm ảnh hưởng trial hiện tại.
- Nếu payment lỗi, user vẫn giữ trạng thái cũ.
```
