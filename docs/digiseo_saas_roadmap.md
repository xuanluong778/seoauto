# Seoauto SaaS Roadmap & Professional System Checklist

Tài liệu này dùng để định hướng nâng cấp Seoauto từ một web app nội bộ thành một sản phẩm SaaS chuyên nghiệp, có thể phát triển thương hiệu và bán cho khách hàng thật.

---

## 1. Mục tiêu sản phẩm

Seoauto nên được định vị không chỉ là một công cụ SEO đơn lẻ, mà là một nền tảng SEO Automation SaaS.

Định vị đề xuất:

```txt
Seoauto là nền tảng SEO AI giúp chủ website, SEOer và agency:
- Quét lỗi Technical SEO
- Research và gom nhóm từ khóa
- Tạo bài viết SEO bằng AI
- Chèn internal link
- Tạo schema JSON-LD
- Đăng bài lên WordPress
- Xuất báo cáo SEO chuyên nghiệp
```

Workflow giá trị nhất:

```txt
Quét website
→ Phát hiện lỗi Technical SEO
→ Research keyword
→ Gom nhóm từ khóa
→ Tạo content brief
→ Viết bài SEO bằng AI
→ Chèn internal link
→ Đăng WordPress
→ Xuất báo cáo
```

---

## 2. Hiện trạng hệ thống

### Backend

```txt
Framework: FastAPI
Server: Uvicorn
ORM: SQLAlchemy 2.x
Database hiện tại: SQLite app.db
Hỗ trợ production DB: PostgreSQL qua DATABASE_URL
Auth: JWT Bearer, bcrypt
Template: Jinja2 SSR
Task nền: Celery + Redis tùy chọn
Crawler: Playwright, requests, BeautifulSoup4
PDF report: ReportLab
Excel: openpyxl
Mã hóa API key: cryptography
```

### AI / LLM

```txt
Provider chính: OpenAI hoặc Anthropic
Content AI mode: auto / off / title_meta_only / content_only
Ảnh AI: OpenAI Image
RAG Knowledge Base: embedding + tài liệu
Chatbot: /chatbot/message
Post-process: blockquote tự động theo số từ
```

### Frontend

```txt
Kiểu frontend: Jinja2 SSR + HTML/CSS/JS
Editor: TinyMCE
Keyword UI: Tailwind CDN
Theme: digiseo-theme.css, digiseo-nav.css
Dark mode: có
i18n: vi / en qua localStorage
```

### Module chính

```txt
Auth
Dashboard Technical SEO
Technical SEO Audit
SEO Score
Content AI
Bulk Content
Keyword Research
Keyword Clustering
Schema JSON-LD
Settings
Admin
Chatbot
WordPress Publish
Knowledge Base
Internal Link
Credits / Trial
```

---

## 3. Đánh giá tổng thể

Hệ thống hiện tại đã có nền kỹ thuật khá mạnh.

Đánh giá:

```txt
70% sản phẩm kỹ thuật
30% SaaS thương mại
```

Phần đã mạnh:

```txt
Technical SEO
Content AI
Keyword Research
Schema
Admin quản lý user/API
WordPress publish
Settings tích hợp
Knowledge Base
Chatbot
```

Phần cần hoàn thiện để thành SaaS:

```txt
Billing thật
Subscription
Usage limit rõ ràng
Payment gateway
Onboarding
Dashboard SaaS cho user
Production deployment
Monitoring/logging
Support ticket
UI/UX polish
Pricing page
Tài liệu API nội bộ
E2E test
```

---

## 4. Ưu tiên nâng cấp quan trọng

## Phase 1: Chuẩn hóa production database

Hiện tại SQLite phù hợp local/dev, không nên dùng cho SaaS production.

Cần chuyển production sang:

```txt
PostgreSQL
```

Lý do:

```txt
Ổn định hơn khi nhiều user dùng cùng lúc
Dữ liệu lớn tốt hơn
Backup dễ hơn
Query mạnh hơn
Dễ scale hơn
Phù hợp SaaS thật
```

Gợi ý dịch vụ:

```txt
Supabase PostgreSQL
Neon
Railway PostgreSQL
Render PostgreSQL
VPS tự cài PostgreSQL
```

Việc cần làm:

```txt
1. Kiểm tra toàn bộ model SQLAlchemy hiện tại
2. Đảm bảo app đọc DATABASE_URL từ env.local
3. Tạo migration an toàn
4. Test local với PostgreSQL
5. Backup SQLite cũ
6. Chạy seed/admin user
7. Test các module chính
```

---

## 5. Phase 2: Thiết kế hệ thống Plan / Subscription

Cần tạo hệ thống gói dịch vụ rõ ràng.

### Gói đề xuất

#### Free Trial

```txt
Dùng thử 7 ngày
3 bài Content AI
3 lần Technical Audit
50 keyword research
Không bulk content
Không publish hàng loạt
Không white-label report
```

#### Starter

```txt
199.000đ/tháng
30 bài Content AI/tháng
30 lần Technical Audit/tháng
1 website WordPress
500 keyword research/tháng
Schema tool
PDF report cơ bản
```

#### Pro

```txt
499.000đ/tháng
150 bài Content AI/tháng
100 lần Technical Audit/tháng
5 website WordPress
5.000 keyword research/tháng
Bulk content
Internal link tự động
Google Sheet export
Content score
```

#### Agency

```txt
1.499.000đ/tháng
Nhiều website
Nhiều client
Bulk content nâng cao
White-label report
API riêng
Team member
Hỗ trợ ưu tiên
```

### Database cần thêm

```txt
plans
subscriptions
usage_limits
usage_events
monthly_usage
payment_transactions
```

---

## 6. Phase 3: Chuẩn hóa Credit / Usage Limit

Mỗi hành động trong app cần được ghi nhận và giới hạn.

### Các event nên tracking

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

### Ví dụ credit

```txt
Tạo 1 bài SEO: 5 credits
Tạo 1 ảnh AI: 10 credits
Quét technical 1 domain nhỏ: 3 credits
Research 100 keyword: 5 credits
Gom nhóm keyword: 5 credits
Đăng WordPress: 1 credit
```

### Bảng usage_events

```txt
id
user_id
event_type
credits_used
feature
metadata
created_at
```

### Bảng monthly_usage

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

Mục tiêu:

```txt
Biết user dùng gì
Biết còn bao nhiêu quota
Biết tính năng nào tốn nhiều API nhất
Biết user nào dùng vượt bất thường
```

---

## 7. Phase 4: Tích hợp Payment Gateway

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

### Luồng thanh toán

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

### Nguyên tắc an toàn

```txt
Không kích hoạt gói nếu webhook chưa xác thực
Không tin dữ liệu từ frontend
Không lưu thông tin thẻ/thông tin nhạy cảm
Payment lỗi thì user giữ trạng thái cũ
Mọi thay đổi gói phải có audit log
```

---

## 8. Phase 5: Dashboard SaaS cho user

Hiện tại /report mạnh về Technical SEO, nhưng SaaS cần một dashboard tổng quan.

Đề xuất route:

```txt
/dashboard
hoặc
/app
```

### Thành phần dashboard

```txt
Gói hiện tại
Credit/quota còn lại
Số bài Content AI đã tạo trong tháng
Số lần Technical Audit đã chạy trong tháng
Số keyword research đã dùng
Website WordPress đã kết nối
Hoạt động gần đây
Cảnh báo gần hết quota
Nút nâng cấp gói
```

### Quick actions

```txt
Quét website
Tạo bài viết SEO
Research keyword
Kết nối WordPress
Tạo schema
Xem báo cáo gần nhất
```

### Empty state cho user mới

```txt
Bạn chưa có dữ liệu nào.
Hãy bắt đầu bằng cách quét website đầu tiên hoặc tạo bài viết SEO đầu tiên.
```

---

## 9. Phase 6: Onboarding user mới

App hiện có nhiều tính năng, user mới dễ rối. Cần onboarding sau đăng ký.

### Luồng onboarding

```txt
Bước 1: Bạn muốn dùng Seoauto để làm gì?
- Audit Technical SEO
- Viết content SEO
- Research keyword
- Đăng bài WordPress
- Làm SEO cho khách hàng

Bước 2: Bạn có website chưa?
- Có
- Chưa

Bước 3: Nhập domain website

Bước 4: Có muốn kết nối WordPress không?

Bước 5: Gợi ý bước tiếp theo
```

Sau onboarding, dashboard hiển thị:

```txt
1. Quét website đầu tiên
2. Research bộ từ khóa đầu tiên
3. Tạo bài SEO đầu tiên
4. Kết nối WordPress
```

---

## 10. Phase 7: Chuẩn hóa UI/UX

Hiện frontend đang là Jinja2 SSR + HTML/CSS/JS. Không cần chuyển sang React ngay, nhưng cần chuẩn hóa UI.

### Cần hạn chế

```txt
CSS inline quá nhiều
Mỗi trang một kiểu button
Mỗi trang một kiểu table
Loading/error không thống nhất
Modal không thống nhất
Form style không thống nhất
```

### Nên tạo thư mục component

```txt
templates/components/
```

Gồm:

```txt
button.html
card.html
modal.html
table.html
input.html
badge.html
toast.html
sidebar.html
empty_state.html
loading.html
pagination.html
```

### Tạo tài liệu

```txt
docs/UI_DESIGN_SYSTEM.md
```

Nội dung:

```txt
Màu chính
Màu phụ
Font
Spacing
Button style
Card style
Table style
Form style
Badge status
Toast message
Dark mode
Mobile responsive
```

---

## 11. Phase 8: Pricing Page

Cần route:

```txt
/pricing
```

Nội dung:

```txt
So sánh Free Trial / Starter / Pro / Agency
Nút dùng thử
Nút nâng cấp
FAQ thanh toán
Chính sách hoàn tiền
Giới hạn từng gói
```

Bảng so sánh nên có:

```txt
Số bài Content AI/tháng
Số lần Technical Audit/tháng
Số keyword research/tháng
Số website WordPress
Bulk Content
Internal Link
Schema Tool
Google Sheet Export
PDF Report
White-label Report
AI Image
Support
```

---

## 12. Phase 9: Admin SaaS Metrics

Admin hiện đã quản lý user/API khá tốt. Cần thêm chỉ số SaaS.

### Admin Overview nên có

```txt
Tổng user
User mới hôm nay
User trial
User active
User trả phí
MRR
Doanh thu tháng này
Tỉ lệ trial → paid
Tổng credit đã dùng
Chi phí AI ước tính
Top user dùng nhiều nhất
Payment failed
API error
```

### Tab admin nên có

```txt
Overview
Users
Subscriptions
Payments
Usage
AI Cost
System Logs
API Keys
Support Tickets
Settings
```

---

## 13. Phase 10: AI Usage Cost Tracking

Vì Seoauto dùng AI nhiều, cần kiểm soát chi phí.

### Bảng ai_usage_logs

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

### Admin cần xem được

```txt
Tổng chi phí AI hôm nay
Chi phí AI theo user
Chi phí AI theo module
User dùng nhiều nhất
Provider lỗi nhiều nhất
Model tốn tiền nhất
```

Mục tiêu:

```txt
Tránh lỗ khi user dùng quá nhiều API Admin pool
Biết tính năng nào tốn chi phí nhất
Tối ưu model phù hợp từng tác vụ
```

---

## 14. Phase 11: Bảo mật API Key

Hiện đã có mã hóa API key bằng cryptography. Cần hoàn thiện thêm.

### Quy tắc

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

### Audit log nên ghi

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

## 15. Phase 12: Production Deployment Checklist

### Server

```txt
HTTPS
Domain thật
Uvicorn/Gunicorn production
Reverse proxy Nginx hoặc Caddy
PostgreSQL
Redis nếu dùng Celery
Backup database hằng ngày
Log rotation
Monitoring uptime
```

### App config

```txt
DEBUG=false
ENV=production
SECRET_KEY mạnh
JWT_SECRET mạnh
CORS cấu hình đúng
Không dùng mock API
Không dùng test payment
Không expose /docs công khai nếu không cần
```

### File upload

```txt
Giới hạn dung lượng ảnh/file
Kiểm tra định dạng file
Không cho upload file nguy hiểm
Lưu file vào object storage
```

Gợi ý storage:

```txt
Cloudflare R2
AWS S3
Supabase Storage
```

---

## 16. Phase 13: Monitoring / Logging

Cần biết hệ thống lỗi ở đâu khi user trả tiền.

### Nên có

```txt
Error logging
Request logging
AI cost logging
Payment logging
Background job logging
Uptime monitoring
```

### Công cụ gợi ý

```txt
Sentry
Better Stack
Logtail
Grafana
UptimeRobot
```

Tối thiểu:

```txt
Sentry cho backend FastAPI
UptimeRobot kiểm tra website sống/chết
Log file riêng cho production
```

---

## 17. Phase 14: Support / Feedback

Cần nơi user báo lỗi và góp ý.

Đề xuất route:

```txt
/support
/feedback
/help
```

Form gồm:

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

Database:

```txt
support_tickets
ticket_messages
```

Ban đầu có thể gửi về Gmail admin trước, sau đó mới làm inbox trong Admin.

---

## 18. Phase 15: Nâng cấp Content AI thành USP chính

Content AI nên là điểm bán hàng mạnh nhất.

### Nên bổ sung

```txt
Content Brief
SERP competitor analysis
People Also Ask
Entity/NLP suggestions
Internal link map
Content score
Duplicate intent warning
Content calendar
Bulk publish schedule
```

### Luồng Content AI chuyên nghiệp

```txt
Nhập keyword
↓
Phân tích SERP
↓
Tạo content brief
↓
Tạo outline
↓
User duyệt outline
↓
Viết bài
↓
Chấm điểm SEO content
↓
Chèn internal link
↓
Tạo ảnh/thumbnail
↓
Đăng WordPress
↓
Theo dõi URL đã publish
```

---

## 19. Phase 16: Nâng cấp Technical SEO Report

Technical SEO nên có báo cáo cho khách hàng/agency.

### Nên thêm

```txt
White-label PDF report
Logo agency
Tên khách hàng
So sánh trước/sau
Lỗi critical/warning/info
Action plan 7 ngày
Action plan 30 ngày
Mức độ ưu tiên
```

### Report nên có

```txt
Executive Summary
SEO Health Score
Top Critical Issues
Indexability
Crawlability
Performance
Metadata
Structured Data
Internal Links
Action Plan
```

---

## 20. Phase 17: E2E Test

Ngoài pytest backend, cần test luồng người dùng thật.

Nên dùng Playwright E2E.

### Luồng cần test

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

Mục tiêu:

```txt
Tránh backend vẫn chạy nhưng UI bấm không được
Tránh update tính năng mới làm hỏng tính năng cũ
```

---

## 21. Thứ tự làm tiếp khuyến nghị

Không nên thêm tính năng lung tung nữa. Nên đi theo thứ tự:

```txt
1. Chuyển production database sang PostgreSQL
2. Chuẩn hóa Plan / Subscription / Usage Limit
3. Tích hợp Payment Gateway
4. Làm Dashboard SaaS tổng quan cho user
5. Làm Pricing Page
6. Làm Onboarding user mới
7. Chuẩn hóa UI Component / Design System
8. Thêm AI Usage Cost Tracking
9. Thêm Production Logging + Sentry
10. Làm White-label Report cho Technical SEO
11. Làm Content Brief + Content Score cho Content AI
12. Thêm E2E Test các luồng chính
13. Tối ưu Admin Dashboard theo SaaS Metrics
14. Thêm Support / Feedback Ticket
15. Deploy production chính thức
```

---

## 22. Prompt cho Cursor: Phase 1 SaaS Foundation

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

---

## 23. Prompt cho Cursor: Payment Gateway

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

---

## 24. Prompt cho Cursor: User Dashboard SaaS

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

---

## 25. Prompt cho Cursor: UI Design System

```txt
Tôi muốn chuẩn hóa UI/UX cho Seoauto để nhìn chuyên nghiệp như SaaS thật.

Bối cảnh:
- Frontend hiện tại dùng Jinja2 SSR + HTML/CSS/JS
- Có theme CSS riêng, dark mode, accent xanh #00e676
- Một số trang còn CSS inline và component chưa thống nhất

Yêu cầu:
1. Audit các template hiện tại.
2. Đề xuất design system đơn giản, không đổi stack.
3. Tạo hoặc chuẩn hóa các component Jinja partial:
   - button
   - card
   - modal
   - table
   - input
   - badge
   - toast
   - loading
   - empty_state
4. Tạo file docs/UI_DESIGN_SYSTEM.md
5. Không sửa toàn bộ UI một lần.
6. Chọn 1 trang ít rủi ro để áp dụng thử trước.
7. Hướng dẫn test giao diện sau khi sửa.

Lưu ý:
- Không làm hỏng JS hiện tại.
- Không đổi sang React/Next.js.
- Không xóa style cũ nếu chưa migration xong.
```

---

## 26. Kết luận

Seoauto đã có nền kỹ thuật mạnh. Việc cần làm tiếp không phải chỉ là thêm tính năng, mà là chuẩn hóa thành SaaS.

Ưu tiên lớn nhất:

```txt
PostgreSQL production
Plan / Subscription
Usage Limit
Payment Gateway
User Dashboard
Pricing Page
Onboarding
Monitoring
AI Cost Tracking
Support
UI/UX polish
```

Định hướng thương hiệu nên đi theo:

```txt
Seoauto - All-in-one SEO Automation SaaS cho cá nhân, chủ website và agency tại Việt Nam.
```
