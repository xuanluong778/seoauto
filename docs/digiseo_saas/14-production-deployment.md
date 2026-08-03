# Production Deployment Checklist

Tài liệu này mô tả checklist deploy Seoauto lên production.

---

## 1. Server

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

---

## 2. App config

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

---

## 3. File upload

```txt
Giới hạn dung lượng ảnh/file
Kiểm tra định dạng file
Không cho upload file nguy hiểm
Lưu file vào object storage
```

Storage gợi ý:

```txt
Cloudflare R2
AWS S3
Supabase Storage
```

---

## 4. Database

```txt
Dùng PostgreSQL
Có backup tự động
Có migration rõ ràng
Có seed admin
Không dùng SQLite production
```

---

## 5. Worker / job nền

Nếu dùng Celery + Redis:

```txt
Chạy worker riêng
Có retry policy
Có log job lỗi
Có timeout job
Có dashboard hoặc log để kiểm tra queue
```

---

## 6. Checklist trước khi public

```txt
Đăng ký chạy được
Đăng nhập chạy được
Trial chạy đúng
Content AI chạy được
Technical Audit chạy được
Keyword Research chạy được
WordPress Publish chạy được
Admin quản lý user chạy được
Payment sandbox chạy được
Email SMTP chạy được
Backup DB hoạt động
Sentry/monitoring hoạt động
```
