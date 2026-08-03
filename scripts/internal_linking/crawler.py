from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.services.internal_linking.models import InternalLinkArticle, InternalLinkChunk

log = logging.getLogger(__name__)


def _normalize_wp_base(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        raise ValueError("wp_site is required")
    p = urlparse(raw if "://" in raw else f"https://{raw}")
    if p.scheme not in {"http", "https"} or not p.netloc:
        raise ValueError(f"Invalid wp_site: {url!r}")
    return f"{p.scheme}://{p.netloc}".rstrip("/")


def _wp_rest_get_json(
    *,
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    timeout_sec: int = 25,
) -> Any:
    try:
        r = session.get(url, params=params, timeout=timeout_sec, headers={"User-Agent": "tooltechnical/il-sync"})
    except requests.RequestException as exc:
        raise RuntimeError(f"WP request failed: {exc}") from exc
    if r.status_code >= 400:
        snippet = (r.text or "")[:600]
        raise RuntimeError(f"WP HTTP {r.status_code} for {url}: {snippet}")
    try:
        return r.json() if r.content else None
    except ValueError as exc:
        raise RuntimeError("WP JSON parse failed") from exc


def _html_to_text(html: str) -> str:
    raw = str(html or "").strip()
    if not raw:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup.find_all(["script", "style", "noscript", "iframe"]):
        tag.decompose()
    txt = soup.get_text(" ", strip=True)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


@dataclass(frozen=True)
class SyncResult:
    wp_site: str
    fetched: int
    upserted_articles: int
    upserted_chunks: int


def _iter_wp_items(
    *,
    wp_site: str,
    wp_type: str,
    per_page: int = 50,
    limit: int = 500,
    status: str = "publish",
) -> Iterable[dict[str, Any]]:
    base = _normalize_wp_base(wp_site)
    if wp_type not in {"post", "page"}:
        raise ValueError("wp_type must be 'post' or 'page'")
    per = max(10, min(int(per_page), 100))
    hard = max(1, min(int(limit), 2000))
    sess = requests.Session()

    page = 1
    fetched = 0
    while True:
        if fetched >= hard:
            break
        url = f"{base}/wp-json/wp/v2/{wp_type}s"
        params = {
            "per_page": min(per, hard - fetched),
            "page": page,
            "status": status,
            "orderby": "modified",
            "order": "desc",
            "_fields": "id,link,slug,title,content,excerpt,modified,status",
        }
        data = _wp_rest_get_json(session=sess, url=url, params=params)
        if not isinstance(data, list) or not data:
            break
        for it in data:
            if not isinstance(it, dict):
                continue
            fetched += 1
            yield it
            if fetched >= hard:
                break
        page += 1


def chunk_html_by_headings(*, html: str) -> list[dict[str, Any]]:
    """
    Chunk HTML into units grouped by heading context.
    Output list items:
      - heading_path: "H1 > H2 > H3"
      - heading_text: nearest heading text (best-effort)
      - html_fragment: HTML snippet
      - text: plain text snippet
    """
    raw = str(html or "").strip()
    if not raw:
        return []
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup.find_all(["script", "style", "noscript", "iframe"]):
        tag.decompose()

    # Track current heading stack
    stack: list[tuple[str, str]] = []
    chunks: list[dict[str, Any]] = []
    buf: list[str] = []
    buf_text: list[str] = []

    def _flush():
        nonlocal buf, buf_text
        frag = "".join(buf).strip()
        txt = re.sub(r"\s+", " ", " ".join(buf_text)).strip()
        if frag and txt:
            heading_path = " > ".join([f"{lvl}:{t}" for (lvl, t) in stack if t])[:900]
            heading_text = (stack[-1][1] if stack else "")[:700]
            chunks.append(
                {
                    "heading_path": heading_path,
                    "heading_text": heading_text,
                    "html_fragment": frag,
                    "text": txt,
                }
            )
        buf = []
        buf_text = []

    # Iterate through top-level nodes in body-like order.
    nodes = list(soup.body.children) if soup.body else list(soup.children)
    for node in nodes:
        if not getattr(node, "name", None):
            continue
        name = str(node.name).lower()
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            _flush()
            lvl = name.upper()
            text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
            # Maintain stack levels
            level_num = int(name[1])
            stack = [x for x in stack if int(x[0][1]) < level_num]
            stack.append((lvl, text))
            continue

        # Prefer paragraphs/lists/tables as chunk-able content
        if name in {"p", "ul", "ol", "table", "blockquote", "div", "section", "article"}:
            frag = str(node)
            txt = node.get_text(" ", strip=True)
            txt = re.sub(r"\s+", " ", txt).strip()
            if txt:
                buf.append(frag)
                buf_text.append(txt)
            # soft boundary: long buffers get flushed to keep chunk sizes reasonable
            if sum(len(t) for t in buf_text) >= 1200:
                _flush()
            continue

    _flush()

    # Final guard: keep only useful chunks
    out = []
    for c in chunks:
        t = str(c.get("text") or "").strip()
        if len(t) < 40:
            continue
        out.append(c)
    return out


def sync_wordpress_site(
    *,
    db: Session,
    wp_site: str,
    wp_types: Iterable[str] = ("post", "page"),
    limit_per_type: int = 400,
    recreate_chunks: bool = True,
) -> SyncResult:
    """
    Crawl WP posts/pages via REST API and upsert into local DB.
    If recreate_chunks=True, we delete and rebuild chunks per article on each sync.
    """
    base = _normalize_wp_base(wp_site)
    fetched = 0
    up_articles = 0
    up_chunks = 0

    now = dt.datetime.now(dt.timezone.utc)

    for wp_type in wp_types:
        for it in _iter_wp_items(wp_site=base, wp_type=str(wp_type), limit=limit_per_type):
            fetched += 1
            wp_id = int(it.get("id") or 0)
            if wp_id <= 0:
                continue
            link = str(it.get("link") or "").strip()
            if not link:
                continue

            title_html = (it.get("title") or {}).get("rendered") if isinstance(it.get("title"), dict) else ""
            excerpt_html = (it.get("excerpt") or {}).get("rendered") if isinstance(it.get("excerpt"), dict) else ""
            content_html = (it.get("content") or {}).get("rendered") if isinstance(it.get("content"), dict) else ""
            title = BeautifulSoup(str(title_html or ""), "html.parser").get_text(" ", strip=True)
            excerpt = BeautifulSoup(str(excerpt_html or ""), "html.parser").get_text(" ", strip=True)
            slug = str(it.get("slug") or "").strip()
            status = str(it.get("status") or "").strip().lower()
            modified_raw = str(it.get("modified") or "").strip()
            modified_dt: Optional[dt.datetime] = None
            if modified_raw:
                try:
                    # WP returns ISO8601 without timezone sometimes; treat as UTC best-effort.
                    modified_dt = dt.datetime.fromisoformat(modified_raw.replace("Z", "+00:00"))
                    if modified_dt.tzinfo is None:
                        modified_dt = modified_dt.replace(tzinfo=dt.timezone.utc)
                except ValueError:
                    modified_dt = None

            existing = (
                db.query(InternalLinkArticle)
                .filter(
                    InternalLinkArticle.wp_site == base,
                    InternalLinkArticle.wp_id == wp_id,
                    InternalLinkArticle.wp_type == wp_type,
                )
                .one_or_none()
            )
            if existing is None:
                existing = InternalLinkArticle(
                    wp_site=base,
                    wp_id=wp_id,
                    wp_type=wp_type,
                    url=link,
                    slug=slug,
                    title=title,
                    excerpt=excerpt,
                    content_html=str(content_html or ""),
                    content_text=_html_to_text(str(content_html or "")),
                    is_published=(status == "publish"),
                    fetched_at=now,
                    updated_at=modified_dt,
                )
                db.add(existing)
                db.flush()
                up_articles += 1
            else:
                # Update fields (best-effort). Avoid rewriting big HTML if unchanged is hard; we update anyway.
                existing.url = link
                existing.slug = slug
                existing.title = title
                existing.excerpt = excerpt
                existing.content_html = str(content_html or "")
                existing.content_text = _html_to_text(str(content_html or ""))
                existing.is_published = status == "publish"
                existing.updated_at = modified_dt
                existing.fetched_at = now
                up_articles += 1

            if recreate_chunks:
                db.query(InternalLinkChunk).filter(InternalLinkChunk.article_id == existing.id).delete()
                db.flush()

            chunks = chunk_html_by_headings(html=existing.content_html)
            for idx, ch in enumerate(chunks):
                c = InternalLinkChunk(
                    article_id=existing.id,
                    chunk_index=idx,
                    heading_path=str(ch.get("heading_path") or ""),
                    heading_text=str(ch.get("heading_text") or ""),
                    text=str(ch.get("text") or ""),
                    html_fragment=str(ch.get("html_fragment") or ""),
                    start_char=0,
                    end_char=0,
                    embedding_model="",
                    embedding_dim=0,
                    embedding=b"",
                    embedded_at=None,
                )
                db.add(c)
                up_chunks += 1

            existing.chunk_count = len(chunks)
            existing.embedded_chunk_count = 0

            # Commit in batches to keep memory reasonable.
            if fetched % 20 == 0:
                db.commit()

    db.commit()
    log.info("IL sync done wp_site=%s fetched=%s up_articles=%s up_chunks=%s", base, fetched, up_articles, up_chunks)
    return SyncResult(wp_site=base, fetched=fetched, upserted_articles=up_articles, upserted_chunks=up_chunks)

