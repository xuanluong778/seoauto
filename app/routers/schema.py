"""Schema Generator UI + JSON API."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.services.schema_api import build_schema_generator_response
from app.services.schema_auto_builder import build_schema_jsonld_string

logger = logging.getLogger(__name__)

router = APIRouter(tags=["schema"])
templates = Jinja2Templates(directory="templates")


@router.get("/schema", response_class=HTMLResponse)
def schema_tool_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="schema_tool.html",
        context={},
    )


@router.get("/api/schema-preview")
def api_schema_preview(
    url: str = Query(..., min_length=4),
    name: str | None = Query(default=None),
    description: str | None = Query(default=None),
) -> JSONResponse:
    return JSONResponse(
        content=json.loads(build_schema_jsonld_string(url=url, name=name, description=description))
    )


@router.post("/api/schema/validate")
async def api_schema_validate(request: Request) -> JSONResponse:
    """Validate JSON-LD client-side output — no persistence, no credit."""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse(status_code=400, content={"detail": "JSON object required"})

    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content={"detail": "JSON object required"})

    json_ld = body.get("json_ld")
    if json_ld is None:
        return JSONResponse(status_code=400, content={"detail": "json_ld required"})

    from app.services.schema_validator import validate_schemas

    schemas: list[dict] = []
    if isinstance(json_ld, list):
        schemas = [n for n in json_ld if isinstance(n, dict)]
    elif isinstance(json_ld, dict):
        graph = json_ld.get("@graph")
        if isinstance(graph, list):
            schemas = [n for n in graph if isinstance(n, dict)]
        elif json_ld.get("@type"):
            schemas = [json_ld]

    validation = validate_schemas(schemas)
    errors = list(validation.get("errors") or [])
    warnings = list(validation.get("warnings") or [])
    score = max(0, 100 - len(errors) * 12 - len(warnings) * 4)
    eligible = [str(s.get("@type")) for s in schemas if s.get("@type")]

    return JSONResponse(
        content={
            "validation": validation,
            "schema_score": score,
            "errors": errors,
            "warnings": warnings,
            "eligible_rich_results": eligible,
            "opportunities": [],
        }
    )


@router.post("/schema-generator")
async def api_schema_generator(request: Request) -> JSONResponse:
    """
    Body JSON: ``url`` | ``html`` | ``text`` (at least one), optional ``seed_keyword``, ``fetch_serp`` (bool, default true).
    """
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse(status_code=400, content={"detail": "JSON object required"})

    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content={"detail": "JSON object required"})

    url = str(body.get("url") or "").strip() or None
    html = str(body.get("html") or "").strip() or None
    text = str(body.get("text") or "").strip() or None
    seed = str(body.get("seed_keyword") or body.get("keyword") or "").strip() or None
    fetch_serp = body.get("fetch_serp")
    fetch_on = True if fetch_serp is None else bool(fetch_serp)

    # Never log URL query secrets, HTML, or text payloads.
    logger.info(
        "schema_generator request has_url=%s has_html=%s has_text=%s fetch_serp=%s",
        bool(url),
        bool(html),
        bool(text),
        fetch_on,
    )

    payload = build_schema_generator_response(
        url=url,
        html=html,
        text=text,
        seed_keyword=seed,
        fetch_serp_flag=fetch_on,
    )
    out = {
        "schemas": payload.get("schemas") or [],
        "primary_schema": payload.get("primary_schema") or {},
        "validation": payload.get("validation") or {},
        "serp_alignment": payload.get("serp_alignment") or {},
        "meta": {
            k: v
            for k, v in payload.items()
            if k not in ("schemas", "primary_schema", "validation", "serp_alignment")
        },
    }
    if not payload.get("ok"):
        return JSONResponse(status_code=422, content=out)
    return JSONResponse(content=out)
