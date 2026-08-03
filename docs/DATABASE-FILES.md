# File database Seoauto (local)

Thư mục gốc dự án: `c:\laragon\www\tooltechnical\`

## Hai file chính

| File | Vai trò |
|------|---------|
| **`app.db`** | Database **đang dùng thật** — FastAPI/SQLAlchemy ghi vào file này khi chạy `run.bat` (mặc định `sqlite:///./app.db`). |
| **`app_backup_before_prompt2.db`** | **Bản sao lưu dự phòng** — snapshot trước khi làm Prompt 2 (seed SaaS, service…). **Không** được app tự ghi; chỉ dùng khi cần khôi phục. |

```
app.db                          ← app đọc/ghi mỗi ngày
app_backup_before_prompt2.db    ← giữ nguyên, chỉ copy khi restore
```

## Cập nhật backup thủ công

PowerShell (dừng server trước nếu có thể):

```powershell
cd c:\laragon\www\tooltechnical
Copy-Item -Path app.db -Destination app_backup_before_prompt2.db -Force
```

Hoặc:

```bat
scripts\backup_db_before_prompt2.bat
```

## Khôi phục từ backup

1. Dừng `run.bat` (Ctrl+C).
2. (Tuỳ chọn) Đổi tên `app.db` hiện tại thành `app.db.broken`.
3. Copy backup thành database đang dùng:

```powershell
Copy-Item -Path app_backup_before_prompt2.db -Destination app.db -Force
```

4. Chạy lại `.\run.bat`.

## Lưu ý

- Cả hai file nằm trong `.gitignore` (`*.db`) — **không** commit lên Git.
- Nên backup lại trước mỗi đợt migration/schema lớn (tên file mới: `app_backup_before_<mô_tả>.db`).
- Production sau này dùng PostgreSQL (`DATABASE_URL`) — file `app.db` chỉ cho local/dev.

## Trạng thái backup Prompt 2

- **Tạo / làm mới:** trước Prompt 2 SaaS  
- **Nội dung:** toàn bộ dữ liệu tại thời điểm copy (users, projects, trial, credit, 6 bảng SaaS Phase 1 nếu đã restart app)
