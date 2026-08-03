# Seoauto Current Stack

Tài liệu này tóm tắt stack kỹ thuật hiện tại của Seoauto.

---

## 1. Backend

```txt
Framework: FastAPI
Server: Uvicorn
ORM: SQLAlchemy 2.x
Database hiện tại: SQLite app.db
Hỗ trợ production DB: PostgreSQL qua DATABASE_URL
Auth: JWT Bearer, bcrypt
OTP đăng ký: Gmail SMTP qua env.local
Template: Jinja2 SSR
API docs: Swagger /docs
Task nền: Celery + Redis tùy chọn
Crawler: Playwright, requests, BeautifulSoup4
PDF report: ReportLab
Excel: openpyxl
Mã hóa API key user: cryptography
ML tùy chọn: sentence-transformers, scikit-learn, numpy
```

---

## 2. AI / LLM

```txt
Provider chính: OpenAI hoặc Anthropic
Content AI mode: auto / off / title_meta_only / content_only
Ảnh AI: OpenAI Image
RAG Knowledge Base: embedding + import tài liệu
Chatbot: /chatbot/message
Post-process: blockquote tự động theo số từ
```

---

## 3. Frontend

```txt
Kiểu frontend: Jinja2 SSR + HTML/CSS/JS
Editor Content AI: TinyMCE
Keyword UI: Tailwind CDN
Theme: digiseo-theme.css, digiseo-nav.css
Dark mode: có
Accent màu chính: xanh #00e676
i18n: vi / en qua localStorage
```

---

## 4. Dev & vận hành local

```txt
Config: env.local
Tests: pytest
Local: Laragon + .venv Python
Start app: run.bat
URL local: http://127.0.0.1:8000
```

---

## 5. Tích hợp bên ngoài

```txt
Google OAuth
Google Search Console API
Google Sheets export
Google Images
WordPress
Haravan
Shopify
Webcake
Keyword volume API tùy chỉnh
SERP fetch
```
