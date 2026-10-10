from collections.abc import Callable
from collections import deque
import time
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from app.services.cost_control.executor import CostControlBypassError, execute_guarded_external
from app.services.cost_control.settings import cost_control_enforced
from app.services.cost_control.types import ExternalApiProvider
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


def classify_request_error(exc: Exception) -> str:
    """Phân loại lỗi kết nối HTTP — DNS, SSL, timeout, v.v."""
    if isinstance(exc, requests.exceptions.TooManyRedirects):
        return "redirect_loop"
    if isinstance(exc, requests.exceptions.SSLError):
        return "ssl_error"
    if isinstance(exc, requests.exceptions.Timeout):
        return "timeout"
    if isinstance(exc, requests.exceptions.ConnectionError):
        msg = str(exc).lower()
        if any(
            token in msg
            for token in (
                "name or service not known",
                "getaddrinfo",
                "failed to resolve",
                "nodename nor servname",
                "name resolution",
            )
        ):
            return "dns_error"
        return "connection_error"
    return "request_failed"


def classify_http_status(status: int) -> str | None:
    if status == 403:
        return "forbidden"
    if status == 401:
        return "unauthorized"
    if 500 <= status < 600:
        return "server_error"
    if 400 <= status < 500:
        return "client_error"
    if 300 <= status < 400:
        return "redirect"
    return None


def robots_url_blocked(url: str, robots_body: str, *, robots_status: int = 200) -> bool | None:
    """True nếu User-agent * bị Disallow cho URL. None khi không đọc được robots."""
    if robots_status != 200 or not (robots_body or "").strip():
        return None
    rp = RobotFileParser()
    rp.parse(robots_body.splitlines())
    try:
        return not rp.can_fetch("*", url)
    except Exception:
        return None


class CrawlTimeoutError(Exception):
    pass


class CrawlStatusError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Non-200 response status: {status_code}")


class CrawlRequestError(Exception):
    pass


def _safe_get(url: str, *, timeout: int = DEFAULT_TIMEOUT_SECONDS, headers=None, allow_redirects: bool = True):
    """SSRF-safe GET for crawl targets."""
    from app.services.url_safety import safe_requests_get, validate_public_http_url
    if validate_public_http_url(url):
        raise CrawlRequestError("URL blocked by SSRF guard")
    # Manual path without auto-follows when needed
    if not allow_redirects:
        return safe_requests_get(url, timeout=float(timeout), headers=headers or DEFAULT_HEADERS, max_redirects=0)
    return safe_requests_get(url, timeout=float(timeout), headers=headers or DEFAULT_HEADERS)


def fetch_html(url: str, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> str:
    from app.services.url_safety import assert_public_http_url, safe_requests_get

    safe_url = assert_public_http_url(url, label="URL crawl")

    def _get() -> requests.Response:
        return safe_requests_get(safe_url, timeout=float(timeout_seconds))

    try:
        if cost_control_enforced():
            response = execute_guarded_external(ExternalApiProvider.CRAWL, "fetch_html", _get)
        else:
            response = _get()
    except CostControlBypassError as exc:
        raise CrawlRequestError("Crawl blocked by cost control") from exc
    except ValueError as exc:
        raise CrawlRequestError(f"URL blocked: {exc}") from exc
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
            response = _safe_get(current, timeout=DEFAULT_TIMEOUT_SECONDS, headers=DEFAULT_HEADERS)
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


def crawl_site_detailed(
    start_url: str,
    max_pages: int = 50,
    *,
    deadline_monotonic: float | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict:
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
    truncated = False

    def _note() -> None:
        if on_progress:
            try:
                on_progress(len(pages), max_pages)
            except Exception:
                pass

    while queue and len(pages) < max_pages:
        if deadline_monotonic is not None and (float(deadline_monotonic) - time.monotonic()) < 3.0:
            truncated = True
            break
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)

        try:
            response = _safe_get(current, timeout=DEFAULT_TIMEOUT_SECONDS, headers=DEFAULT_HEADERS, allow_redirects=True)
        except requests.exceptions.RequestException as exc:
            kind = classify_request_error(exc)
            pages.append(
                {
                    "url": current,
                    "status": 0,
                    "html": "",
                    "internal_links": [],
                    "redirect_history": [current],
                    "error_kind": kind,
                    "crawl_status": "timeout" if kind == "timeout" else "error",
                }
            )
            _note()
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
            _note()
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
        _note()

    return {
        "pages": pages,
        "total": len(pages),
        "edges": edges,
        "domain": base_domain,
        "partial_data": truncated,
        "truncated": truncated,
    }


def check_internal_link_status(url: str, timeout_seconds: float | None = None) -> dict:
    to = timeout_seconds if timeout_seconds is not None else LINK_CHECK_TIMEOUT_SECONDS
    for attempt in range(2):
        try:
            response = _safe_get(
                url,
                timeout=to,
                headers=LINK_CHECK_HEADERS,
                allow_redirects=True,
            )
        except requests.exceptions.RequestException as exc:
            if attempt == 0:
                time.sleep(0.45)
                continue
            error_kind = classify_request_error(exc)
            return {
                "url": url,
                "status": 0,
                "is_broken": True,
                "chain": [url],
                "error_kind": error_kind,
            }
        chain = [resp.url for resp in response.history] + [response.url]
        status = response.status_code
        error_kind = classify_http_status(status)
        keys = []
        loop = False
        for hop in chain:
            k = (hop or "").rstrip("/").lower()
            if k in keys:
                loop = True
                break
            keys.append(k)
        if loop:
            error_kind = "redirect_loop"
        return {
            "url": url,
            "status": status,
            "is_broken": status >= 400 or loop,
            "chain": chain,
            "error_kind": error_kind,
        }


def parse_robots_txt(base_url: str) -> dict:
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        response = _safe_get(robots_url, timeout=DEFAULT_TIMEOUT_SECONDS, headers=DEFAULT_HEADERS)
    except requests.exceptions.RequestException as exc:
        return {
            "url": robots_url,
            "status": 0,
            "disallow": [],
            "allow": [],
            "sitemaps": [],
            "body_preview": "",
            "error_kind": classify_request_error(exc),
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

    last_error: dict | None = None
    for sitemap_url in candidate_urls:
        try:
            response = _safe_get(sitemap_url, timeout=DEFAULT_TIMEOUT_SECONDS, headers=DEFAULT_HEADERS)
        except requests.exceptions.RequestException as exc:
            last_error = {
                "url": sitemap_url,
                "http_status": 0,
                "parse_error": False,
                "error_kind": classify_request_error(exc),
            }
            continue
        if response.status_code != 200:
            last_error = {
                "url": sitemap_url,
                "http_status": response.status_code,
                "parse_error": False,
                "error_kind": classify_http_status(response.status_code),
            }
            continue
        try:
            root = ET.fromstring(response.text)
        except ET.ParseError:
            last_error = {"url": sitemap_url, "http_status": 200, "parse_error": True, "error_kind": "parse_error"}
            continue
        locs = [elem.text.strip() for elem in root.iter() if elem.tag.endswith("loc") and elem.text]
        return {
            "url": sitemap_url,
            "status": 200,
            "urls": locs,
            "parse_error": False,
            "http_status": 200,
        }

    return {
        "url": candidate_urls[0] if candidate_urls else "",
        "status": 0,
        "urls": [],
        "parse_error": bool(last_error and last_error.get("parse_error")),
        "last_error": last_error,
    }
