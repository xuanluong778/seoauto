# Seoauto — Tài liệu theo dự án nhỏ

Tài liệu chia theo **module** (mỗi tab / tính năng lớn = một file). Cập nhật: 2026-05-20.

## Chạy local

```bat
cd c:\laragon\www\tooltechnical
.\run.bat
```

Mở: http://127.0.0.1:8000 — Config: `env.local` (không commit).

---

## Mục lục

| # | File | Mô tả ngắn |
|---|------|------------|
| 0 | [00-overview-stack.md](./00-overview-stack.md) | Stack tổng, kiến trúc, DB, phân quyền |
| 1 | [01-home-landing.md](./01-home-landing.md) | Trang chủ `/`, marketing, modal đăng nhập |
| 2 | [02-dashboard-report.md](./02-dashboard-report.md) | Dashboard `/report`, export, GSC |
| 3 | [03-technical-seo-tool.md](./03-technical-seo-tool.md) | Phân tích Technical `/tool`, crawl, checklist |
| 4 | [04-seo-url-score.md](./04-seo-url-score.md) | Chấm điểm SEO `/tool/seo-score` |
| 5 | [05-content-ai.md](./05-content-ai.md) | Content AI `/content-ai`, bulk, publish |
| 6 | [06-keyword-research.md](./06-keyword-research.md) | Từ khóa `/keywords/tools/research` |
| 7 | [07-schema-generator.md](./07-schema-generator.md) | Schema JSON-LD `/schema` |
| 8 | [08-settings.md](./08-settings.md) | Cài đặt `/settings`, API keys, KB, publish |
| 9 | [09-admin.md](./09-admin.md) | Quản trị `/admin` (role admin) |
| 10 | [10-auth-permissions.md](./10-auth-permissions.md) | JWT, OTP, trial, API access |
| 11 | [11-chatbot.md](./11-chatbot.md) | Chatbot nổi toàn site |
| 12 | [12-internal-links.md](./12-internal-links.md) | Internal linking + WP sync |
| 13 | [13-shared-infrastructure.md](./13-shared-infrastructure.md) | Router, workers, i18n, theme |

---

## Menu chính (URL)

| Tab UI | URL |
|--------|-----|
| Trang chủ | `/` |
| Dashboard | `/report` |
| Phân tích Technical | `/tool` |
| Chấm điểm SEO | `/tool/seo-score` |
| Content AI | `/content-ai` |
| Từ khóa | `/keywords/tools/research` |
| Schema | `/schema` |
| Cài đặt | `/settings` |
| Quản trị viên | `/admin` (ẩn nếu không phải admin) |

---

## Tài liệu kỹ thuật khác (đã có)

- [keyword-data-sources.md](../keyword-data-sources.md)
- [search_behavior_layer.md](../search_behavior_layer.md)
- [serp_intelligence_layer.md](../serp_intelligence_layer.md)
- [topical_authority_layer.md](../topical_authority_layer.md)

---

## Trạng thái tổng thể

| Mức | Module |
|-----|--------|
| Hoàn chỉnh | Technical, Report, Schema, Settings shell, Admin |
| Rất mạnh | Content AI, Keyword |
| Phụ thuộc config | Volume keyword, GSC, Google OAuth, payment/credits |
