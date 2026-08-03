# 00 — Tổng quan & Stack

## Tên dự án

**Seoauto**

## Kiến trúc

```
Browser (Jinja2 HTML + vanilla JS)
        ↓ JWT Bearer
FastAPI (main.py) + routers
        ↓
SQLAlchemy → SQLite (app.db) hoặc PostgreSQL
        ↓
Dịch vụ: crawl, LLM, keyword, publish, GSC...
```

## Stack

| Lớp | Công nghệ |
|-----|-----------|
| API | FastAPI, Uvicorn, Pydantic |
| DB | SQLAlchemy 2, SQLite / PostgreSQL |
| Auth | JWT (`python-jose`), bcrypt |
| Template | Jinja2 |
| Crawl | Playwright, requests, BeautifulSoup4 |
| AI | OpenAI / Anthropic (`llm_content_writer.py`) |
| ML (tùy chọn) | sentence-transformers, scikit-learn, numpy |
| Task queue (tùy chọn) | Celery + Redis |
| Export | ReportLab (PDF), openpyxl (Excel) |
| Mã hóa key user | cryptography |

## Entry point

| File | Vai trò |
|------|---------|
| `main.py` | App FastAPI, mount routers, `/`, `/health` |
| `run.bat` | venv + pip + uvicorn port 8000 |
| `env.local` | Biến môi trường (API keys, SMTP, DB…) |
| `requirements.txt` | Dependencies Python |

## Routers đăng ký (`main.py`)

| Router | Prefix / path |
|--------|----------------|
| `settings_api_router` | `/api/settings` |
| `analyze_router` | `/analyze` |
| `pages_router` | pages + `/content-ai/*` |
| `report_router` | `/report`, `/api/audit/*` |
| `integrations_router` | tích hợp |
| `serp_intel_router` | SERP intelligence |
| `keyword_intel_router` | keyword intel |
| `keywords_router` | `/keywords/*` |
| `wp_bulk_router` | WP bulk update |
| `user_files_router` | upload user files |
| `internal_links_router` | `/internal-links/*` |
| `auth_router` | `/auth/*` |
| `projects_router` | `/projects` |
| `admin_router` | `/admin` |
| `admin_api_router` | `/admin/api`, `/api/admin` |
| `chatbot_router` | `/chatbot`, `/api/chatbot` |

## Models DB chính

- `users`, `user_trials`, `user_api_keys`
- SEO audits / `projects`
- Content AI projects, bulk jobs
- `keyword_research_projects`, cluster jobs
- `knowledge_bases`, publishing sites
- `security_audit_logs`, `credit_ledger`

## Phân quyền (tóm tắt)

Chi tiết: [10-auth-permissions.md](./10-auth-permissions.md)

- **Role:** `admin`, `user`, `editor`, `viewer`
- **API on** (`api_access_enabled`): admin cấp → dùng AI không cần trial
- **API Admin pool** (`use_admin_api_pool`): dùng key hệ thống trong `env.local`
- **Trial 7 ngày:** kích hoạt khi user thêm API key hợp lệ lần đầu (nếu chưa được admin cấp API)

## Liên kết

→ [README.md](./README.md)
