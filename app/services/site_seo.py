"""Central SEO metadata, robots.txt and sitemap.xml for seoauto.vn."""

from __future__ import annotations

import json
import os
from datetime import date
from typing import Any
from urllib.parse import urljoin

SITE_BASE_URL = (os.getenv("APP_BASE_URL") or "https://seoauto.vn").rstrip("/")
GOOGLE_SITE_VERIFICATION = (os.getenv("GOOGLE_SITE_VERIFICATION") or "").strip()
GOOGLE_SITE_VERIFICATION_HTML_FILE = (os.getenv("GOOGLE_SITE_VERIFICATION_HTML_FILE") or "").strip()
GOOGLE_SITE_VERIFICATION_HTML_BODY = (os.getenv("GOOGLE_SITE_VERIFICATION_HTML_BODY") or "").strip()

PRIVATE_PREFIXES = (
    "/admin",
    "/api",
    "/auth",
    "/login",
    "/register",
    "/dashboard",
    "/billing",
    "/account",
    "/account-billing",
    "/report",
    "/settings",
    "/social-auto",
    "/chatbot-cskh",
    "/google-map-seo",
    "/rank-tracking",
    "/chatbot",
)

ROBOTS_DISALLOW = (
    "/admin",
    "/api",
    "/login",
    "/register",
    "/dashboard",
    "/billing",
    "/account",
    "/account-billing",
    "/report",
    "/settings",
    "/social-auto",
    "/chatbot-cskh",
    "/google-map-seo",
    "/auth",
    "/chatbot",
    "/static",
)

SITEMAP_ENTRIES: list[dict[str, str | float]] = [
    {"loc": "/", "changefreq": "weekly", "priority": "1.0"},
    {"loc": "/tool", "changefreq": "weekly", "priority": "0.9"},
    {"loc": "/content-ai", "changefreq": "weekly", "priority": "0.9"},
    {"loc": "/keywords/tools/research", "changefreq": "weekly", "priority": "0.85"},
    {"loc": "/keywords/tools/clustering", "changefreq": "weekly", "priority": "0.85"},
    {"loc": "/index-control", "changefreq": "weekly", "priority": "0.85"},
    {"loc": "/pricing", "changefreq": "monthly", "priority": "0.8"},
    {"loc": "/privacy", "changefreq": "yearly", "priority": "0.3"},
    {"loc": "/terms", "changefreq": "yearly", "priority": "0.3"},
]

PAGE_SEO: dict[str, dict[str, Any]] = {
    "/": {
        "title": "Tool SEO tự động SEOAuto - Phần mềm SEO AI cho website",
        "description": (
            "SEOAuto là phần mềm SEO tự động hỗ trợ audit technical SEO, viết bài SEO AI, "
            "nghiên cứu từ khóa, gom nhóm từ khóa và kiểm tra index website."
        ),
        "og_type": "website",
    },
    "/tool": {
        "title": "Công cụ kiểm tra SEO Technical tự động - SEOAuto",
        "description": (
            "Công cụ SEO tự động quét lỗi technical SEO, kiểm tra title, meta, heading, "
            "sitemap, robots, canonical và chấm điểm SEO Score cho từng URL."
        ),
    },
    "/content-ai": {
        "title": "Phần mềm viết bài SEO AI tự động - SEOAuto",
        "description": (
            "Phần mềm viết bài SEO AI: tạo outline, draft nội dung chuẩn SEO, tối ưu heading "
            "và xuất bản WordPress/Haravan trên nền tảng SEOAuto."
        ),
    },
    "/keywords/tools/research": {
        "title": "Công cụ nghiên cứu từ khóa SEO tự động - SEOAuto",
        "description": (
            "Nghiên cứu từ khóa SEO tự động: volume, CPC, competition, search intent "
            "và gợi ý từ khóa liên quan từ seed keyword."
        ),
    },
    "/keywords/tools/clustering": {
        "title": "Công cụ gom nhóm từ khóa SEO tự động - SEOAuto",
        "description": (
            "Gom nhóm từ khóa theo SERP overlap, tách keyword chính/phụ và gợi ý cụm chủ đề "
            "để lập kế hoạch content SEO."
        ),
    },
    "/index-control": {
        "title": "Công cụ kiểm tra index Google tự động - SEOAuto",
        "description": (
            "Kiểm tra index Google và gửi tín hiệu lập chỉ mục URL. Theo dõi trạng thái index "
            "và lịch sử submit indexing trên SEOAuto."
        ),
    },
    "/google-map-seo": {
        "title": "Công cụ Google Map SEO & tối ưu Google Business Profile - SEOAuto",
        "description": (
            "Kiểm tra, tối ưu hồ sơ Google Map, quản lý review, bài đăng, ảnh và theo dõi đối thủ "
            "Local SEO trên SEOAuto."
        ),
    },
    "/pricing": {
        "title": "Bảng giá phần mềm SEO SEOAuto",
        "description": (
            "Bảng giá gói phần mềm SEO tự động SEOAuto — credit audit, nghiên cứu từ khóa, "
            "viết bài AI và các công cụ SEO cho doanh nghiệp."
        ),
    },
    "/privacy": {
        "title": "Chính sách bảo mật — SEOAuto",
        "description": "Chính sách bảo mật SEOAuto — cách chúng tôi sử dụng dữ liệu Google Search Console và Google OAuth.",
    },
    "/terms": {
        "title": "Điều khoản sử dụng — SEOAuto",
        "description": "Điều khoản sử dụng dịch vụ phần mềm SEO SEOAuto.",
    },
}


def _normalize_path(path: str) -> str:
    p = (path or "/").split("?", 1)[0].rstrip("/") or "/"
    return p


def is_private_path(path: str) -> bool:
    p = _normalize_path(path)
    if p in PRIVATE_PREFIXES:
        return True
    return any(p == pref or p.startswith(pref + "/") for pref in PRIVATE_PREFIXES)


def canonical_url(path: str) -> str:
    return urljoin(SITE_BASE_URL + "/", _normalize_path(path).lstrip("/"))


def _organization_schema() -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "SEOAuto",
        "url": SITE_BASE_URL,
        "logo": f"{SITE_BASE_URL}/static/images/seoauto-logo.png",
        "description": (
            "SEOAuto — phần mềm SEO tự động và công cụ SEO AI cho audit technical, "
            "nghiên cứu từ khóa và viết bài SEO."
        ),
    }


def _software_application_schema() -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": "SEOAuto",
        "applicationCategory": "BusinessApplication",
        "operatingSystem": "Web",
        "url": SITE_BASE_URL,
        "description": PAGE_SEO["/"]["description"],
        "offers": {
            "@type": "Offer",
            "price": "0",
            "priceCurrency": "VND",
            "description": "Dùng thử miễn phí với gói trial",
        },
        "publisher": {
            "@type": "Organization",
            "name": "SEOAuto",
            "url": SITE_BASE_URL,
        },
    }


def _breadcrumb_schema(items: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i + 1,
                "name": item["name"],
                "item": item["url"],
            }
            for i, item in enumerate(items)
        ],
    }


def _home_faq_schema() -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": "SEOAuto là tool SEO tự động gì?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": (
                        "SEOAuto là phần mềm SEO tự động trên nền web, gồm audit technical SEO, "
                        "nghiên cứu từ khóa, gom nhóm từ khóa, viết bài SEO AI và kiểm tra index Google."
                    ),
                },
            },
            {
                "@type": "Question",
                "name": "Phần mềm SEO SEOAuto phù hợp cho ai?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": (
                        "Phù hợp cho SEOer, agency và doanh nghiệp cần công cụ SEO tự động "
                        "để audit website, lập kế hoạch từ khóa và sản xuất nội dung chuẩn SEO."
                    ),
                },
            },
            {
                "@type": "Question",
                "name": "Có dùng thử miễn phí không?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "Có — bạn có thể đăng ký trial để dùng thử các công cụ SEO trên SEOAuto trước khi nâng gói.",
                },
            },
        ],
    }


def _json_ld_scripts(path: str, override: dict[str, Any] | None = None) -> list[str]:
    scripts: list[str] = []
    extra = (override or {}).get("json_ld") or []

    if path == "/":
        scripts.append(json.dumps(_organization_schema(), ensure_ascii=False))
        scripts.append(json.dumps(_software_application_schema(), ensure_ascii=False))
        scripts.append(json.dumps(_home_faq_schema(), ensure_ascii=False))
        faq = (override or {}).get("faq_schema")
        if faq:
            scripts.append(json.dumps(faq, ensure_ascii=False))
    elif path in PAGE_SEO:
        crumbs = [
            {"name": "Trang chủ", "url": SITE_BASE_URL},
            {"name": PAGE_SEO[path]["title"].split(" - ")[0], "url": canonical_url(path)},
        ]
        scripts.append(json.dumps(_breadcrumb_schema(crumbs), ensure_ascii=False))

    for block in extra:
        scripts.append(json.dumps(block, ensure_ascii=False))
    return scripts


def build_seo_context(path: str, override: dict[str, Any] | None = None) -> dict[str, Any]:
    p = _normalize_path(path)
    base = dict(PAGE_SEO.get(p, {}))
    if override:
        base.update({k: v for k, v in override.items() if v is not None})

    private = is_private_path(p)
    robots = "noindex,nofollow" if private else "index,follow"

    title = base.get("title") or "SEOAuto — Phần mềm SEO tự động"
    description = base.get("description") or (
        "SEOAuto — công cụ SEO tự động: audit technical, nghiên cứu từ khóa, viết bài SEO AI."
    )
    canonical = base.get("canonical") or canonical_url(p)
    og_type = base.get("og_type") or "website"
    og_image = base.get("og_image") or f"{SITE_BASE_URL}/static/images/seoauto-logo.png"

    return {
        "title": title,
        "description": description,
        "canonical": canonical,
        "robots": robots,
        "og_type": og_type,
        "og_title": base.get("og_title") or title,
        "og_description": base.get("og_description") or description,
        "og_url": canonical,
        "og_image": og_image,
        "og_site_name": "SEOAuto",
        "twitter_card": "summary_large_image",
        "google_site_verification": GOOGLE_SITE_VERIFICATION,
        "json_ld_scripts": _json_ld_scripts(p, override),
        "is_private": private,
    }


def resolve_page_seo_for_request(request: Any, seo_override: dict[str, Any] | None = None) -> dict[str, Any]:
    path = getattr(getattr(request, "url", None), "path", "/") or "/"
    return build_seo_context(path, seo_override)


def build_robots_txt() -> str:
    lines = [
        "User-agent: *",
        "Allow: /",
    ]
    for rule in ROBOTS_DISALLOW:
        lines.append(f"Disallow: {rule}")
    lines.append("")
    lines.append(f"Sitemap: {SITE_BASE_URL}/sitemap.xml")
    lines.append("")
    return "\n".join(lines)


def build_sitemap_xml() -> str:
    today = date.today().isoformat()
    urls: list[str] = []
    for entry in SITEMAP_ENTRIES:
        loc = canonical_url(str(entry["loc"]))
        changefreq = entry.get("changefreq", "weekly")
        priority = entry.get("priority", "0.5")
        lastmod = entry.get("lastmod", today)
        urls.append(
            "  <url>\n"
            f"    <loc>{loc}</loc>\n"
            f"    <lastmod>{lastmod}</lastmod>\n"
            f"    <changefreq>{changefreq}</changefreq>\n"
            f"    <priority>{priority}</priority>\n"
            "  </url>"
        )
    body = "\n".join(urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}\n"
        "</urlset>\n"
    )


def install_jinja_seo_globals() -> None:
    from fastapi.templating import Jinja2Templates

    if getattr(Jinja2Templates, "_seo_globals_installed", False):
        return

    _orig_init = Jinja2Templates.__init__

    def _patched_init(self: Jinja2Templates, *args: Any, **kwargs: Any) -> None:
        _orig_init(self, *args, **kwargs)
        self.env.globals["resolve_page_seo"] = resolve_page_seo_for_request

    Jinja2Templates.__init__ = _patched_init  # type: ignore[method-assign]
    Jinja2Templates._seo_globals_installed = True
