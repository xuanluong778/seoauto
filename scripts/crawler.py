from collections import deque
import time
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from app.services.seo_crawl_enrichment import enrich_crawl_page_record


DEFAULT_TIMEOUT_SECONDS = 8
LINK_CHECK_TIMEOUT_SECONDS = 12
# Nhiều host/WAF chặn User-Agent kiểu bot; GET kiểm tra liên kết dùng UA trình duyệt để giảm HTTP 0 giả.
LINK_CHECK_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi,en;q=0.9",
}
DEFAULT_HEADERS = {
    "User-Agent": "SEO-Crawler/1.0 (+https://example.com/bot)",
}


class CrawlTimeoutError(Exception):
    pass


class CrawlStatusError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Non-200 response status: {status_code}")


class CrawlRequestError(Exception):
    pass


def fetch_html(url: str, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> str:
    try:
        response = requests.get(url, timeout=timeout_seconds)
    except requests.exceptions.Timeout as exc:
        raise CrawlTimeoutError("Request timed out") from exc
    except requests.exceptions.RequestException as exc:
        raise CrawlRequestError("Request failed") from exc

    if response.status_code != 200:
        raise CrawlStatusError(response.status_code)

    return response.text


def normalize_url(raw_url: str) -> str:
    value = raw_url.strip()
    if not value:
        raise ValueError("URL cannot be empty")
    if "://" not in value:
        value = f"https://{value}"

    parsed = urlparse(value)
    hostname = parsed.hostname
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not hostname:
        raise ValueError("Invalid URL")
    if hostname != "localhost" and "." not in hostname:
        raise ValueError("Invalid URL")

    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"

    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        path=path,
        params="",
        fragment="",
    )
    return urlunparse(normalized)


def _is_html_response(response: requests.Response) -> bool:
    content_type = response.headers.get("Content-Type", "").lower()
    return "text/html" in content_type


def _http_crawl_enrichment(response: requests.Response, normalized_final_url: str, body: str) -> dict:
    """HTTP-only transport: raw === rendered; same SEO layer for consistent keys."""
    chain = [resp.url for resp in response.history] + [response.url]
    try:
        final_n = normalize_url(response.url)
    except ValueError:
        final_n = normalized_final_url
    hdrs = {k: v for k, v in response.headers.items()}
    raw = body or ""
    enr = enrich_crawl_page_record(
        rendered_html=raw,
        raw_html=raw,
        final_effective_url=final_n,
        raw_final_url=final_n,
        playwright_status=int(response.status_code),
        raw_http_status=int(response.status_code),
        playwright_headers=hdrs,
        raw_headers=hdrs,
    )
    rvr = dict(enr.get("raw_vs_rendered") or {})
    rvr["transport"] = "http_only_no_js"
    enr["raw_vs_rendered"] = rvr
    return {
        "raw_html": raw,
        "raw_http_status": int(response.status_code),
        "raw_redirect_history": chain,
        "raw_response_headers": hdrs,
        **enr,
    }


def _extract_links(base_url: str, html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        absolute = urljoin(base_url, anchor["href"])
        links.append(absolute)
    return links


def crawl_site(start_url: str, max_pages: int = 50) -> dict:
    if max_pages <= 0:
        return {"pages": [], "total": 0}

    try:
        normalized_start = normalize_url(start_url)
    except ValueError:
        return {"pages": [], "total": 0}

    base_domain = urlparse(normalized_start).netloc

    queue: deque[str] = deque([normalized_start])
    seen: set[str] = {normalized_start}
    visited: set[str] = set()
    pages: list[dict] = []

    while queue and len(pages) < max_pages:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)

        try:
            response = requests.get(
                current,
                timeout=DEFAULT_TIMEOUT_SECONDS,
                headers=DEFAULT_HEADERS,
            )
        except requests.exceptions.Timeout:
            continue
        except requests.exceptions.RequestException:
            continue

        if response.status_code != 200:
            continue

        if not _is_html_response(response):
            continue

        pages.append({"url": current, "status": response.status_code})
        for link in _extract_links(current, response.text):
            try:
                normalized_link = normalize_url(link)
            except ValueError:
                continue

            parsed_link = urlparse(normalized_link)
            if parsed_link.netloc != base_domain:
                continue
            if normalized_link in visited or normalized_link in seen:
                continue
            seen.add(normalized_link)
            queue.append(normalized_link)

    return {"pages": pages, "total": len(pages)}


def crawl_site_detailed(start_url: str, max_pages: int = 50) -> dict:
    if max_pages <= 0:
        return {"pages": [], "total": 0, "edges": [], "domain": ""}

    try:
        normalized_start = normalize_url(start_url)
    except ValueError:
        return {"pages": [], "total": 0, "edges": [], "domain": ""}

    base_domain = urlparse(normalized_start).netloc
    queue: deque[str] = deque([normalized_start])
    seen: set[str] = {normalized_start}
    visited: set[str] = set()
    pages: list[dict] = []
    edges: list[dict] = []

    while queue and len(pages) < max_pages:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)

        try:
            response = requests.get(
                current,
                timeout=DEFAULT_TIMEOUT_SECONDS,
                headers=DEFAULT_HEADERS,
                allow_redirects=True,
            )
        except requests.exceptions.RequestException:
            continue

        final_url = response.url
        try:
            normalized_final_url = normalize_url(final_url)
        except ValueError:
            normalized_final_url = current

        if response.status_code != 200 or not _is_html_response(response):
            dbg = _http_crawl_enrichment(response, normalized_final_url, response.text or "")
            pages.append(
                {
                    "url": current,
                    "status": response.status_code,
                    "html": "",
                    "internal_links": [],
                    "redirect_history": [resp.url for resp in response.history] + [response.url],
                    "response_headers": dbg["raw_response_headers"],
                    **dbg,
                }
            )
            continue

        internal_links: list[str] = []
        for link in _extract_links(normalized_final_url, response.text):
            try:
                normalized_link = normalize_url(link)
            except ValueError:
                continue
            if urlparse(normalized_link).netloc != base_domain:
                continue
            internal_links.append(normalized_link)
            edges.append({"from": normalized_final_url, "to": normalized_link})
            if normalized_link not in seen and normalized_link not in visited:
                seen.add(normalized_link)
                queue.append(normalized_link)

        dbg = _http_crawl_enrichment(response, normalized_final_url, response.text or "")
        pages.append(
            {
                "url": normalized_final_url,
                "status": response.status_code,
                "html": response.text,
                "internal_links": sorted(set(internal_links)),
                "redirect_history": [resp.url for resp in response.history] + [response.url],
                "response_headers": dbg["raw_response_headers"],
                **dbg,
            }
        )

    return {"pages": pages, "total": len(pages), "edges": edges, "domain": base_domain}


def check_internal_link_status(url: str, timeout_seconds: float | None = None) -> dict:
    to = timeout_seconds if timeout_seconds is not None else LINK_CHECK_TIMEOUT_SECONDS
    for attempt in range(2):
        try:
            response = requests.get(
                url,
                timeout=to,
                headers=LINK_CHECK_HEADERS,
                allow_redirects=True,
            )
        except requests.exceptions.RequestException:
            if attempt == 0:
                time.sleep(0.45)
                continue
            return {"url": url, "status": 0, "is_broken": True, "chain": [url]}
        chain = [resp.url for resp in response.history] + [response.url]
        return {
            "url": url,
            "status": response.status_code,
            "is_broken": response.status_code >= 400,
            "chain": chain,
        }


def parse_robots_txt(base_url: str) -> dict:
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        response = requests.get(robots_url, timeout=DEFAULT_TIMEOUT_SECONDS, headers=DEFAULT_HEADERS)
    except requests.exceptions.RequestException:
        return {
            "url": robots_url,
            "status": 0,
            "disallow": [],
            "allow": [],
            "sitemaps": [],
            "body_preview": "",
        }

    body = (response.text or "") if response.status_code == 200 else ""
    disallow: list[str] = []
    allow: list[str] = []
    sitemaps: list[str] = []
    for line in body.splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.startswith("#"):
            continue
        lower = cleaned.lower()
        if lower.startswith("disallow:"):
            disallow.append(cleaned.split(":", 1)[1].strip())
        elif lower.startswith("allow:"):
            allow.append(cleaned.split(":", 1)[1].strip())
        elif lower.startswith("sitemap:"):
            sitemaps.append(cleaned.split(":", 1)[1].strip())
    preview = body if len(body) <= 8000 else body[:8000] + "\n…"
    return {
        "url": robots_url,
        "status": response.status_code,
        "disallow": disallow,
        "allow": allow,
        "sitemaps": sitemaps,
        "body_preview": preview,
    }


def parse_sitemap_xml(base_url: str, robots_sitemaps: list[str] | None = None) -> dict:
    parsed = urlparse(base_url)
    candidate_urls = list(robots_sitemaps or [])
    if not candidate_urls:
        candidate_urls = [
            f"{parsed.scheme}://{parsed.netloc}/sitemap.xml",
            f"{parsed.scheme}://{parsed.netloc}/sitemap_index.xml",
        ]

    for sitemap_url in candidate_urls:
        try:
            response = requests.get(sitemap_url, timeout=DEFAULT_TIMEOUT_SECONDS, headers=DEFAULT_HEADERS)
        except requests.exceptions.RequestException:
            continue
        if response.status_code != 200:
            continue
        try:
            root = ET.fromstring(response.text)
        except ET.ParseError:
            continue
        locs = [elem.text.strip() for elem in root.iter() if elem.tag.endswith("loc") and elem.text]
        return {"url": sitemap_url, "status": 200, "urls": locs}

    return {"url": candidate_urls[0] if candidate_urls else "", "status": 0, "urls": []}
