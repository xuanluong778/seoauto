# Production Database Roadmap

Tài liệu này mô tả việc chuyển Seoauto từ SQLite sang PostgreSQL để phù hợp với SaaS production.

---

## 1. Hiện trạng

Hiện tại hệ thống dùng:

```txt
SQLite app.db
```

Và có hỗ trợ:

```txt
PostgreSQL qua DATABASE_URL
```

SQLite phù hợp local/dev, nhưng không nên dùng làm database production cho SaaS.

---

## 2. Database production nên dùng

Nên chuyển sang:

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

---

## 3. Dịch vụ gợi ý

```txt
Supabase PostgreSQL
Neon
Railway PostgreSQL
Render PostgreSQL
VPS tự cài PostgreSQL
```

Khuyến nghị cho giai đoạn đầu:

```txt
Supabase hoặc Neon
```

---

## 4. Việc cần làm

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

## 5. Checklist test sau khi chuyển DB

```txt
Đăng ký user
Đăng nhập user
Admin xem danh sách user
Tạo Content AI project
Chạy Technical Audit
Research keyword
Lưu API key
Kết nối WordPress
Tạo Knowledge Base
Kiểm tra trial/credit
```
