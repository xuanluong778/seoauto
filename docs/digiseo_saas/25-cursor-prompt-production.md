# Cursor Prompt - Production Readiness

Dùng prompt này trong Cursor để kiểm tra Seoauto trước khi deploy production.

---

```txt
Tôi muốn kiểm tra Seoauto đã sẵn sàng deploy production chưa.

Bối cảnh:
- Backend FastAPI + Uvicorn
- Database hiện tại hỗ trợ PostgreSQL qua DATABASE_URL
- App có auth, admin, Content AI, Technical SEO, Keyword Research, Settings, WordPress Publish
- Có env.local, API keys, trial, credits

Yêu cầu:
1. Audit toàn bộ cấu hình production.
2. Kiểm tra các biến môi trường bắt buộc.
3. Kiểm tra DEBUG/ENV/SECRET_KEY/JWT_SECRET/CORS.
4. Kiểm tra app có đang dùng mock/dev mode ở đâu không.
5. Kiểm tra /docs có nên tắt hoặc bảo vệ ở production không.
6. Kiểm tra file upload có giới hạn chưa.
7. Kiểm tra logging production.
8. Kiểm tra database backup/migration.
9. Tạo checklist production readiness.
10. Không sửa code ngay nếu chưa phân tích xong.

Lưu ý:
- Không làm hỏng local dev.
- Nếu cần thay đổi config, hãy đề xuất rõ từng bước.
- Ưu tiên an toàn, bảo mật và ổn định.
```
