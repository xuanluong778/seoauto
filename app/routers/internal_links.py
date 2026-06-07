from __future__ import annotations

import logging
import re
from typing import Any, Optional

from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.services.auth import get_current_user
from app.services.internal_linking.anchor_generator import generate_anchor_variations
from app.services.internal_linking.crawler import sync_wordpress_site
from app.services.internal_linking.embeddings import DEFAULT_MODEL, embed_chunks_for_site
from app.services.internal_linking.injector import InjectionRules, LinkSuggestion, inject_internal_links
from app.services.internal_linking.similarity_service import SuggestOptions, suggest_related_articles_for_text

log = logging.getLogger(__name__)

router = APIRouter(prefix="/content-ai/internal-links", tags=["content-ai-internal-links"])


class SyncRequest(BaseModel):
    wp_site: str = Field(..., description="WordPress base URL, e.g. https://example.com")
    limit_per_type: int = Field(400, ge=1, le=2000)
    async_mode: bool = Field(True, description="Run sync via Celery")


class EmbedRequest(BaseModel):
    wp_site: str
    model_name: str | None = Field(default=None)
    only_missing: bool = True
    async_mode: bool = True


class SuggestRequest(BaseModel):
    wp_site: str
    source_html: str = Field(..., description="HTML to analyze and link from")
    exclude_url: str | None = Field(default=None, description="URL of the current page to exclude from suggestions")
    primary_keyword: str | None = Field(default=None, description="Optional keyword to help anchor generation")
    max_results: int = Field(8, ge=1, le=8)
    min_score: float = Field(0.30, ge=0.0, le=1.0)


class ApplyRequest(BaseModel):
    html: str
    suggestions: list[dict[str, Any]]
    max_links: int = Field(8, ge=0, le=12)
    min_word_gap: int = Field(80, ge=0, le=400)


def _html_to_text_for_embedding(html: str) -> str:
    raw = str(html or "").strip()
    if not raw:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup.find_all(["script", "style", "noscript", "iframe"]):
        tag.decompose()
    txt = soup.get_text(" ", strip=True)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt[:9000]


@router.post("/sync")
def internal_links_sync(
    payload: SyncRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    wp_site = str(payload.wp_site or "").strip()
    if not wp_site:
        raise HTTPException(status_code=400, detail="wp_site is required")
    if payload.async_mode:
        from app.queue.celery_app import celery_app

        task = celery_app.send_task("internal_links.sync_site", args=[wp_site, int(payload.limit_per_type)])
        return JSONResponse(content={"ok": True, "queued": True, "task_id": task.id})
    try:
        res = sync_wordpress_site(db=db, wp_site=wp_site, limit_per_type=int(payload.limit_per_type), recreate_chunks=True)
        return JSONResponse(
            content={
                "ok": True,
                "queued": False,
                "wp_site": res.wp_site,
                "fetched": res.fetched,
                "upserted_articles": res.upserted_articles,
                "upserted_chunks": res.upserted_chunks,
            }
        )
    except Exception as exc:
        log.exception("sync failed")
        raise HTTPException(status_code=502, detail=str(exc)[:900]) from exc


@router.post("/embed")
def internal_links_embed(
    payload: EmbedRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    wp_site = str(payload.wp_site or "").strip()
    if not wp_site:
        raise HTTPException(status_code=400, detail="wp_site is required")
    model = (payload.model_name or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    if payload.async_mode:
        from app.queue.celery_app import celery_app

        task = celery_app.send_task("internal_links.embed_site", args=[wp_site, model, bool(payload.only_missing)])
        return JSONResponse(content={"ok": True, "queued": True, "task_id": task.id, "model": model})
    try:
        res = embed_chunks_for_site(db=db, wp_site=wp_site, model_name=model, only_missing=bool(payload.only_missing))
        return JSONResponse(
            content={
                "ok": True,
                "queued": False,
                "wp_site": wp_site,
                "embedding_model": res.embedding_model,
                "embedded_chunks": res.embedded_chunks,
                "skipped_chunks": res.skipped_chunks,
            }
        )
    except Exception as exc:
        log.exception("embed failed")
        raise HTTPException(status_code=502, detail=str(exc)[:900]) from exc


@router.post("/suggest")
def internal_links_suggest(
    payload: SuggestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    wp_site = str(payload.wp_site or "").strip()
    if not wp_site:
        raise HTTPException(status_code=400, detail="wp_site is required")
    src_text = _html_to_text_for_embedding(payload.source_html)
    if not src_text:
        raise HTTPException(status_code=400, detail="source_html is empty")

    opt = SuggestOptions(
        k=36,
        min_score=float(payload.min_score),
        max_results=int(payload.max_results),
        max_per_article=1,
        model_name=DEFAULT_MODEL,
    )
    hits = suggest_related_articles_for_text(
        db=db,
        wp_site=wp_site,
        source_text=src_text,
        exclude_url=str(payload.exclude_url or "").strip(),
        options=opt,
    )

    # Generate an anchor per hit (natural variations) and pick one that occurs in the source HTML if possible.
    suggestions: list[dict[str, Any]] = []
    for h in hits:
        # Use a representative sentence-ish context by taking a slice of source text.
        ctx = src_text[:300]
        anchors = generate_anchor_variations(
            context_sentence=ctx,
            target_title=h.title,
            primary_keyword=str(payload.primary_keyword or "").strip(),
            max_candidates=6,
        )
        # pick first candidate; injection step will only insert when anchor appears
        anchor = anchors[0].text if anchors else (h.title.split(" | ")[0].strip()[:70] if h.title else "")
        suggestions.append(
            {
                "url": h.url,
                "title": h.title,
                "heading": h.heading_text,
                "score": h.score,
                "anchor_text": anchor,
                "anchor_candidates": [a.text for a in anchors],
            }
        )

    return JSONResponse(content={"ok": True, "count": len(suggestions), "items": suggestions})


@router.post("/apply")
def internal_links_apply(
    payload: ApplyRequest,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    raw = str(payload.html or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="html is required")
    max_links = int(payload.max_links)
    min_gap = int(payload.min_word_gap)
    sugg: list[LinkSuggestion] = []
    for it in payload.suggestions or []:
        if not isinstance(it, dict):
            continue
        url = str(it.get("url") or "").strip()
        title = str(it.get("title") or "").strip()
        anchor = str(it.get("anchor_text") or "").strip()
        score = float(it.get("score") or 0.0)
        if url and anchor:
            sugg.append(LinkSuggestion(url=url, title=title, anchor_text=anchor, score=score))

    out_html, inserted = inject_internal_links(
        html=raw,
        suggestions=sugg,
        rules=InjectionRules(max_links=max_links, min_word_gap=min_gap),
    )
    return JSONResponse(content={"ok": True, "inserted": len(inserted), "links": inserted, "content_html": out_html})

