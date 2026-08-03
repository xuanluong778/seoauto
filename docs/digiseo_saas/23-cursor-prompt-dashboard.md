# Cursor Prompt - User Dashboard

Dùng prompt này trong Cursor để tạo dashboard SaaS tổng quan cho user Seoauto.

---

```txt
Tôi muốn tạo dashboard SaaS tổng quan cho user Seoauto.

Bối cảnh:
App hiện có các module Technical SEO, Content AI, Keyword Research, Schema, WordPress Publish, Credits, Trial.

Yêu cầu dashboard:
1. Hiển thị gói hiện tại của user.
2. Hiển thị credit/quota còn lại.
3. Hiển thị số bài Content AI đã tạo trong tháng.
4. Hiển thị số lần Technical Audit đã chạy trong tháng.
5. Hiển thị số keyword research đã dùng.
6. Hiển thị website WordPress đã kết nối.
7. Hiển thị các hoạt động gần đây.
8. Có khu vực Quick Actions:
   - Quét website
   - Tạo bài viết SEO
   - Research keyword
   - Kết nối WordPress
9. Có empty state đẹp cho user mới.
10. Có CTA nâng cấp gói nếu gần hết quota.

Lưu ý:
- Dùng Jinja2 hiện tại, không chuyển sang SPA.
- Tận dụng CSS/theme hiện có.
- Không làm hỏng /report hiện tại.
- Nếu cần route mới, đề xuất là /dashboard hoặc /app.
```
