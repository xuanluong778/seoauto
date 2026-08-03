"""
Keyword Intelligence UI + JSON API.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.services.keyword_intelligence_api import build_keyword_intelligence_response

router = APIRouter(tags=["keyword-intelligence"])
templates = Jinja2Templates(directory="templates")


@router.get("/api/keyword-intelligence")
def api_keyword_intelligence(
    seed_keyword: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    url: str | None = Query(default=None),
) -> JSONResponse:
    """
    Query params: ``seed_keyword`` (optional), ``domain``, ``url``.

    GSC queries are not passed via GET (use POST body extension later); connect GSC in /tool first for crawl flows.
    """
    payload = build_keyword_intelligence_response(
        seed_keyword=seed_keyword,
        domain=domain,
        url=url,
        gsc_queries=None,
        pages=None,
        ranking_decision_v3=None,
    )
    return JSONResponse(content=payload)


@router.post("/api/keyword-intelligence")
async def api_keyword_intelligence_post(request: Request) -> JSONResponse:
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content={"detail": "JSON object required"})
    seeds = body.get("seed_keywords") or body.get("seeds")
    if isinstance(seeds, str):
        seeds = [s.strip() for s in seeds.split(",") if s.strip()]
    if not isinstance(seeds, list):
        seeds = []
    gsc = body.get("gsc_queries")
    if gsc is not None and not isinstance(gsc, list):
        gsc = None
    payload = build_keyword_intelligence_response(
        seed_keyword=str(body.get("seed_keyword") or "").strip() or None,
        seed_keywords=[str(s).strip() for s in seeds if str(s).strip()],
        domain=str(body.get("domain") or "").strip() or None,
        url=str(body.get("url") or "").strip() or None,
        gsc_queries=gsc,
        pages=body.get("pages") if isinstance(body.get("pages"), list) else None,
        ranking_decision_v3=body.get("ranking_decision_v3") if isinstance(body.get("ranking_decision_v3"), dict) else None,
    )
    return JSONResponse(content=payload)


@router.get("/keyword-intelligence", response_class=HTMLResponse)
def keyword_intelligence_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="keyword_intelligence.html",
        context={"initial_json": "{}"},
    )
