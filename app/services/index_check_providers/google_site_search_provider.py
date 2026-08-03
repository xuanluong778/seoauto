from __future__ import annotations

import logging
import os
import random
import re
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from app.services.index_check_providers.base import (
    INDEX_STATUS_CAPTCHA_REQUIRED,
    INDEX_STATUS_INDEX,
    INDEX_STATUS_NO_INDEX,
    INDEX_STATUS_PENDING_RETRY,
    INDEX_STATUS_UNKNOWN,
    BaseIndexCheckProvider,
    IndexCheckProviderResult,
    utc_now_iso,
)
from app.services.index_check_providers.url_match import (
    build_match_evidence,
    decode_url,
    is_leaked_query_echo,
    normalize_index_url,
    sanitize_extracted_url,
    urls_exact_index_match,
)

_LOG = logging.getLogger(__name__)

_GOOGLE_SEARCH_URL = "https://www.google.com/search"
_CAPTCHA_RE = re.compile(
    r"unusual traffic|systems have detected|not a robot|captcha|sorry/index|consent\.google",
    re.I,
)
_NO_RESULT_RE = re.compile(
    r"did not match any documents|không tìm thấy kết quả|no results found|"
    r"không có kết quả nào|your search .* did not match",
    re.I,
)
_BLOCK_RE = re.compile(r"access denied|403 forbidden|blocked|enable javascript", re.I)
_JS_WALL_RE = re.compile(r"enablejs|noscript|javascript", re.I)

_RELIABLE_SERP_SOURCES = frozenset({"google_cse", "serpapi", "dataforseo", "custom"})


class GoogleSiteSearchProvider(BaseIndexCheckProvider):
    def __init__(self, *, timeout: float | None = None, session: requests.Session | None = None) -> None:
        default_timeout = float(os.getenv("INDEX_CONTROL_CHECK_URL_TIMEOUT", "12") or "12")
        self.timeout = float(timeout if timeout is not None else default_timeout)
        self.session = session or requests.Session()
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        ]

    def _query_for(self, url: str, *, query_url: str | None = None) -> str:
        return f"site:{(query_url or url).strip()}"

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": random.choice(self.user_agents),
            "Accept-Language": "vi,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml",
            "Cache-Control": "no-cache",
        }

    def _is_organic_link(self, anchor) -> bool:
        if anchor is None or getattr(anchor, "name", "") != "a":
            return False
        href = str(anchor.get("href") or "").strip()
        if not href or href.startswith("#") or href.startswith("/search"):
            return False
        if is_leaked_query_echo(href):
            return False
        if not anchor.find("h3"):
            return False
        parent_g = anchor.find_parent("div", class_="g")
        parent_yu = anchor.find_parent("div", class_="yuRUbf")
        if not parent_g and not parent_yu:
            return False
        if parent_g is not None and parent_yu is None:
            cite = parent_g.select_one("cite, .iUh4url, span.VuuXrf")
            if cite is None and not anchor.get("data-ved"):
                return False
        return True

    def _extract_organic_results(self, html: str) -> list[dict[str, str]]:
        soup = BeautifulSoup(html or "", "html.parser")
        out: list[dict[str, str]] = []
        seen: set[str] = set()

        def add(url: str, title: str = "", cite: str = "") -> None:
            href = sanitize_extracted_url(url)
            if not href.startswith("http") or is_leaked_query_echo(url):
                return
            key = normalize_index_url(href)
            if not key or key in seen:
                return
            seen.add(key)
            out.append({"url": href, "title": (title or "")[:240], "cite": cite[:240]})

        for anchor in soup.select("div.yuRUbf > a[href], div.g a[href]"):
            if not self._is_organic_link(anchor):
                continue
            href = str(anchor.get("href") or "")
            h3 = anchor.find("h3")
            title = h3.get_text(" ", strip=True) if h3 else ""
            cite_text = ""
            parent_g = anchor.find_parent("div", class_="g")
            if parent_g:
                cite_node = parent_g.select_one("cite, .iUh4url, span.VuuXrf")
                if cite_node:
                    cite_text = cite_node.get_text(" ", strip=True)
            add(href, title, cite_text)

        return out

    def _match_target(
        self,
        target: str,
        results: list[dict[str, str]],
    ) -> tuple[dict[str, str] | None, str, list[str]]:
        candidates: list[str] = []
        for item in results:
            href = sanitize_extracted_url(str(item.get("url") or ""))
            if href:
                candidates.append(href)
            matched, match_type = urls_exact_index_match(target, href)
            if matched:
                out = dict(item)
                out["url"] = href
                return out, match_type, candidates
        return None, "none", candidates

    def _result(
        self,
        *,
        target: str,
        query: str,
        index_status: str,
        reason: str,
        matched: dict[str, str] | None = None,
        match_type: str = "none",
        candidate_urls: list[str] | None = None,
        checked_at: str,
        retry_count: int,
        extra: str = "",
    ) -> dict[str, Any]:
        candidates = list(candidate_urls or [])
        matched_url = (matched or {}).get("url") or ""
        evidence = build_match_evidence(
            query=query,
            target_url=target,
            candidate_urls=candidates,
            matched_url=matched_url,
            match_type=match_type,
            reason=reason,
            extra=extra,
        )
        return IndexCheckProviderResult(
            url=target,
            query=query,
            index_status=index_status,
            matched_url=matched_url,
            title=(matched or {}).get("title") or "",
            reason=reason,
            checked_at=checked_at,
            retry_count=retry_count,
            evidence=evidence,
            target_url_normalized=normalize_index_url(target),
            candidate_urls=candidates[:20],
            match_type=match_type,
        ).to_dict()

    def _check_via_dataforseo_site(self, target: str, query: str) -> dict[str, Any] | None:
        try:
            from app.services import dataforseo_client
        except Exception:
            return None

        if not dataforseo_client.is_dataforseo_enabled() or dataforseo_client.get_basic_auth() is None:
            return None

        loc_name = (os.getenv("DATAFORSEO_LOCATION_NAME") or "Vietnam").strip()
        lang_name = (os.getenv("DATAFORSEO_LANGUAGE_NAME") or "Vietnamese").strip()
        checked_at = utc_now_iso()

        try:
            res = dataforseo_client.google_serp_live_advanced(
                query,
                location_name=loc_name,
                language_name=lang_name,
                device="desktop",
                depth=10,
            )
        except Exception as exc:
            _LOG.warning("index_check_dataforseo_error: %s", type(exc).__name__)
            return None

        if res.get("mock") and not res.get("fallback_mock"):
            return None

        if res.get("fallback_mock") and str(res.get("error") or "") == "empty_result":
            return self._result(
                target=target,
                query=query,
                index_status=INDEX_STATUS_NO_INDEX,
                reason="Google không trả organic result cho truy vấn site: (DataForSEO).",
                match_type="none",
                candidate_urls=[],
                checked_at=checked_at,
                retry_count=0,
                extra="serp_source=dataforseo;organic=0;empty_result=1",
            )

        if res.get("mock"):
            return None

        organic: list[dict[str, str]] = []
        for it in res.get("items") or []:
            if str(it.get("type") or "").lower() != "organic":
                continue
            href = str(it.get("url") or "").strip()
            if href:
                organic.append({"url": href, "title": str(it.get("title") or "")[:240], "cite": href})

        matched, match_type, candidates = self._match_target(target, organic)
        extra = f"serp_source=dataforseo;organic={len(organic)}"
        if matched:
            return self._result(
                target=target,
                query=query,
                index_status=INDEX_STATUS_INDEX,
                reason="Tìm thấy organic result URL khớp chính xác (DataForSEO).",
                matched=matched,
                match_type=match_type,
                candidate_urls=candidates,
                checked_at=checked_at,
                retry_count=0,
                extra=extra,
            )

        return self._result(
            target=target,
            query=query,
            index_status=INDEX_STATUS_NO_INDEX,
            reason="DataForSEO có organic result nhưng không URL nào khớp chính xác target.",
            match_type="none",
            candidate_urls=candidates,
            checked_at=checked_at,
            retry_count=0,
            extra=extra,
        )

    def _check_via_serp_fetcher(self, target: str, query: str) -> dict[str, Any] | None:
        if os.getenv("SERP_FETCH_ENABLED", "0").lower() not in ("1", "true", "yes"):
            return None
        try:
            from app.services.serp_fetcher import fetch_serp_for_keyword

            snap = fetch_serp_for_keyword(query, top_n=10, use_cache=True)
        except Exception as exc:
            _LOG.warning("index_check_serp_fetch_error: %s", type(exc).__name__)
            return None

        source = str(snap.get("source") or "none")
        urls = [str(u) for u in (snap.get("serp_urls") or []) if u]
        titles = [str(t) for t in (snap.get("titles") or [])]
        extra = f"serp_source={source};hits={len(urls)}"

        if source in ("disabled", "none", "empty"):
            return None

        results = [
            {"url": urls[i], "title": titles[i] if i < len(titles) else "", "cite": urls[i]}
            for i in range(len(urls))
        ]
        matched, match_type, candidates = self._match_target(target, results)
        checked_at = utc_now_iso()

        if matched:
            return self._result(
                target=target,
                query=query,
                index_status=INDEX_STATUS_INDEX,
                reason="Tìm thấy organic result URL khớp chính xác (SERP API).",
                matched=matched,
                match_type=match_type,
                candidate_urls=candidates,
                checked_at=checked_at,
                retry_count=0,
                extra=extra,
            )

        if source in _RELIABLE_SERP_SOURCES:
            return self._result(
                target=target,
                query=query,
                index_status=INDEX_STATUS_NO_INDEX,
                reason="SERP API có kết quả nhưng không có organic URL khớp chính xác target.",
                match_type="none",
                candidate_urls=candidates,
                checked_at=checked_at,
                retry_count=0,
                extra=extra,
            )

        return None

    def _scrape_google(self, target: str, query: str, *, retry_count: int) -> dict[str, Any]:
        checked_at = utc_now_iso()
        try:
            r = self.session.get(
                _GOOGLE_SEARCH_URL,
                params={"q": query, "hl": "vi", "num": 10, "safe": "off", "pws": "0"},
                headers=self._headers(),
                timeout=self.timeout,
            )
            body = r.text or ""
            final_url = str(r.url or "")
        except requests.Timeout:
            return self._result(
                target=target,
                query=query,
                index_status=INDEX_STATUS_PENDING_RETRY,
                reason="Google search timeout — thử lại sau.",
                checked_at=checked_at,
                retry_count=retry_count + 1,
                extra="scrape=timeout",
            )
        except requests.RequestException as exc:
            return self._result(
                target=target,
                query=query,
                index_status=INDEX_STATUS_UNKNOWN,
                reason=f"Lỗi mạng khi truy vấn Google: {type(exc).__name__}",
                checked_at=checked_at,
                retry_count=retry_count + 1,
                extra=f"scrape=network_error:{type(exc).__name__}",
            )

        extra = f"scrape=http={r.status_code};bytes={len(body)};final={final_url[:120]}"

        if r.status_code in (429, 503) or _CAPTCHA_RE.search(body) or "/sorry/" in final_url:
            return self._result(
                target=target,
                query=query,
                index_status=INDEX_STATUS_CAPTCHA_REQUIRED,
                reason="Google yêu cầu captcha hoặc chặn tạm thời.",
                checked_at=checked_at,
                retry_count=retry_count + 1,
                extra=extra,
            )

        if r.status_code >= 400 or _BLOCK_RE.search(body[:2000]):
            return self._result(
                target=target,
                query=query,
                index_status=INDEX_STATUS_UNKNOWN,
                reason="Google trả về phản hồi bị chặn hoặc bất thường.",
                checked_at=checked_at,
                retry_count=retry_count + 1,
                extra=extra,
            )

        if not body.strip():
            return self._result(
                target=target,
                query=query,
                index_status=INDEX_STATUS_UNKNOWN,
                reason="Google trả về response rỗng.",
                checked_at=checked_at,
                retry_count=retry_count + 1,
                extra=extra,
            )

        results = self._extract_organic_results(body)
        extra = f"{extra};organic={len(results)}"
        matched, match_type, candidates = self._match_target(target, results)

        if matched:
            return self._result(
                target=target,
                query=query,
                index_status=INDEX_STATUS_INDEX,
                reason="Tìm thấy organic result URL khớp chính xác trong Google site:.",
                matched=matched,
                match_type=match_type,
                candidate_urls=candidates,
                checked_at=checked_at,
                retry_count=retry_count,
                extra=extra,
            )

        if _NO_RESULT_RE.search(body):
            return self._result(
                target=target,
                query=query,
                index_status=INDEX_STATUS_NO_INDEX,
                reason="Google báo không có kết quả cho truy vấn site:.",
                match_type="none",
                candidate_urls=candidates,
                checked_at=checked_at,
                retry_count=retry_count,
                extra=extra,
            )

        if results:
            return self._result(
                target=target,
                query=query,
                index_status=INDEX_STATUS_NO_INDEX,
                reason="Google có organic result nhưng không URL nào khớp chính xác target.",
                match_type="none",
                candidate_urls=candidates,
                checked_at=checked_at,
                retry_count=retry_count,
                extra=extra,
            )

        if _JS_WALL_RE.search(body[:4000]) and len(body) < 120000:
            return self._result(
                target=target,
                query=query,
                index_status=INDEX_STATUS_UNKNOWN,
                reason="Google yêu cầu JavaScript — không parse được SERP HTML.",
                match_type="none",
                candidate_urls=[],
                checked_at=checked_at,
                retry_count=retry_count,
                extra=extra,
            )

        if len(body) > 2500:
            return self._result(
                target=target,
                query=query,
                index_status=INDEX_STATUS_UNKNOWN,
                reason="Không parse được organic result — có thể bị chặn hoặc đổi giao diện.",
                match_type="none",
                candidate_urls=[],
                checked_at=checked_at,
                retry_count=retry_count,
                extra=extra,
            )

        return self._result(
            target=target,
            query=query,
            index_status=INDEX_STATUS_UNKNOWN,
            reason="Không xác định được kết quả Google.",
            match_type="none",
            candidate_urls=[],
            checked_at=checked_at,
            retry_count=retry_count,
            extra=extra,
        )

    def check_url(self, url: str, *, retry_count: int = 0, query_url: str | None = None) -> dict[str, Any]:
        target = decode_url((query_url or url).strip())
        query = self._query_for(target, query_url=target)

        dfs_row = self._check_via_dataforseo_site(target, query)
        if dfs_row is not None:
            dfs_row["retry_count"] = int(dfs_row.get("retry_count") or retry_count)
            return dfs_row

        serp_row = self._check_via_serp_fetcher(target, query)
        if serp_row is not None:
            serp_row["retry_count"] = int(serp_row.get("retry_count") or retry_count)
            return serp_row

        return self._scrape_google(target, query, retry_count=retry_count)
