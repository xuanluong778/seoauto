# Cursor Prompt - SaaS Foundation

Dùng prompt này trong Cursor để bắt đầu xây nền SaaS cho Seoauto.

---

```txt
Tôi muốn nâng cấp Seoauto từ SEO tool nội bộ thành SaaS chuyên nghiệp.

Bối cảnh:
- Backend FastAPI + SQLAlchemy
- Database hiện tại SQLite, hỗ trợ PostgreSQL qua DATABASE_URL
- Frontend Jinja2 SSR + HTML/CSS/JS
- Có các module: Technical SEO, Content AI, Keyword Research, Schema, Settings, Admin, API key, Trial, Credits
- Hiện có khung credits và admin grant nhưng chưa có payment gateway thật

Mục tiêu:
Thiết kế hệ thống SaaS gồm Plan, Subscription, Usage Limit, Payment, User Dashboard và Admin SaaS Metrics.

Yêu cầu:
1. Đọc codebase hiện tại trước khi sửa.
2. Tìm các model liên quan đến users, credit_ledger, user_trials, trial_key_claims, user_api_keys.
3. Đề xuất schema database mới cho:
   - plans
   - subscriptions
   - usage_events
   - monthly_usage
   - payment_transactions
4. Không xóa logic trial/credits hiện tại.
5. Đề xuất cách migrate an toàn từ hệ thống hiện tại sang SaaS billing.
6. Chia implementation thành nhiều phase nhỏ.
7. Phase 1 chỉ tạo database models + migration + service layer, chưa cần payment gateway.
8. Sau khi làm xong, hướng dẫn tôi test từng bước.

Lưu ý:
- Không làm hỏng các module Content AI, Technical SEO, Keyword, Admin hiện tại.
- Không đổi stack frontend.
- Không tự ý chuyển sang React/Next.js.
- Ưu tiên kiến trúc dễ bảo trì, phù hợp production SaaS.
```
