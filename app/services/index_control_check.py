"""Index Control — check index (MVP mock per url_type)."""

from __future__ import annotations

from typing import Any, Literal

UrlType = Literal["main_site", "web20", "web2", "social_entity", "social"]

URL_TYPES: frozenset[str] = frozenset({"main_site", "web20", "web2", "social_entity", "social"})

URL_TYPE_LABELS: dict[str, str] = {
    "main_site": "Website chính",
    "web20": "Web 2.0",
    "social_entity": "Social / Entity",
}

_MOCK_POOL: dict[str, list[dict[str, Any]]] = {
    "main_site": [
        {
            "status": "Indexed",
            "status_class": "ok",
            "primary_error": "—",
            "severity": "low",
            "severity_label": "Thấp",
            "hint": "URL đã index — duy trì nội dung và internal link.",
            "action": "Xem GSC",
            "checks": {
                "http": "200",
                "noindex": "Không",
                "robots": "Allow",
                "canonical": "OK",
                "sitemap": "Có",
            },
        },
        {
            "status": "Not indexed",
            "status_class": "warn",
            "primary_error": "Discovered – not indexed",
            "severity": "medium",
            "severity_label": "Trung bình",
            "hint": "Gửi IndexNow, kiểm tra sitemap và internal link tới URL.",
            "action": "IndexNow",
            "checks": {
                "http": "200",
                "noindex": "Không",
                "robots": "Allow",
                "canonical": "OK",
                "sitemap": "Không",
            },
        },
        {
            "status": "Blocked",
            "status_class": "err",
            "primary_error": "HTTP 404",
            "severity": "high",
            "severity_label": "Cao",
            "hint": "Sửa redirect 301 hoặc gỡ URL khỏi sitemap.",
            "action": "Doctor",
            "checks": {
                "http": "404",
                "noindex": "Không",
                "robots": "Allow",
                "canonical": "—",
                "sitemap": "Không",
            },
        },
    ],
    "web20": [
        {
            "status": "Indexed",
            "status_class": "ok",
            "primary_error": "—",
            "severity": "low",
            "severity_label": "Thấp",
            "hint": "Bài Web 2.0 đã index — duy trì link về site chính.",
            "action": "Xem GSC",
            "checks": {
                "http": "200",
                "noindex": "Không",
                "canonical": "Self",
                "crawl": "OK",
            },
        },
        {
            "status": "Not indexed",
            "status_class": "warn",
            "primary_error": "Crawl budget thấp",
            "severity": "medium",
            "severity_label": "Trung bình",
            "hint": "Thêm internal link từ profile Web 2.0 và chia sẻ URL công khai.",
            "action": "Doctor",
            "checks": {
                "http": "200",
                "noindex": "Không",
                "canonical": "Trỏ site chính",
                "crawl": "Chậm",
            },
        },
        {
            "status": "Blocked",
            "status_class": "err",
            "primary_error": "noindex",
            "severity": "high",
            "severity_label": "Cao",
            "hint": "Nền tảng đặt noindex — chuyển sang bài public hoặc custom domain.",
            "action": "Doctor",
            "checks": {
                "http": "200",
                "noindex": "Có",
                "canonical": "—",
                "crawl": "Hạn chế",
            },
        },
    ],
    "social_entity": [
        {
            "status": "Live",
            "status_class": "ok",
            "primary_error": "—",
            "severity": "low",
            "severity_label": "Thấp",
            "hint": "URL hoạt động — theo dõi index brand entity định kỳ.",
            "action": "Xem GSC",
            "checks": {
                "alive": "Sống",
                "crawl": "Một phần",
                "basic_status": "Public",
            },
        },
        {
            "status": "Limited",
            "status_class": "warn",
            "primary_error": "Login wall",
            "severity": "medium",
            "severity_label": "Trung bình",
            "hint": "Trang yêu cầu đăng nhập — Google khó index toàn bộ nội dung.",
            "action": "Doctor",
            "checks": {
                "alive": "Sống",
                "crawl": "Hạn chế",
                "basic_status": "Login required",
            },
        },
        {
            "status": "Dead",
            "status_class": "err",
            "primary_error": "HTTP 404 / removed",
            "severity": "high",
            "severity_label": "Cao",
            "hint": "URL không tồn tại — cập nhật link entity trên site chính.",
            "action": "Doctor",
            "checks": {
                "alive": "Chết",
                "crawl": "Không",
                "basic_status": "404",
            },
        },
    ],
}


def normalize_url_type(raw: str | None) -> str:
    value = (raw or "main_site").strip().lower()
    if value == "web2":
        return "web20"
    if value == "social":
        return "social_entity"
    if value not in URL_TYPES:
        return "main_site"
    return value


def check_index_urls(
    *,
    url_type: str,
    website: str | None,
    urls: list[str],
    max_urls: int = 20,
) -> dict[str, Any]:
    """Mock check — trả về kết quả theo loại URL."""
    ut = normalize_url_type(url_type)
    pool = _MOCK_POOL[ut]
    clean_urls = [u.strip() for u in urls if u and u.strip()][:max_urls]

    items: list[dict[str, Any]] = []
    for i, url in enumerate(clean_urls):
        sample = dict(pool[i % len(pool)])
        sample["url"] = url
        items.append(sample)

    return {
        "demo": True,
        "url_type": ut,
        "url_type_label": URL_TYPE_LABELS[ut],
        "website": (website or "").strip() or None,
        "count": len(items),
        "items": items,
    }
