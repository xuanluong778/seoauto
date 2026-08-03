"""Public SEO routes: robots.txt, sitemap.xml, Google Search Console verification."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response

from app.services.site_seo import (
    GOOGLE_SITE_VERIFICATION_HTML_BODY,
    GOOGLE_SITE_VERIFICATION_HTML_FILE,
    build_robots_txt,
    build_sitemap_xml,
)

router = APIRouter(tags=["seo"])


@router.get("/robots.txt", response_class=Response)
def robots_txt() -> Response:
    return Response(content=build_robots_txt(), media_type="text/plain; charset=utf-8")


@router.get("/sitemap.xml", response_class=Response)
def sitemap_xml() -> Response:
    return Response(content=build_sitemap_xml(), media_type="application/xml; charset=utf-8")


def _register_google_verification_route() -> None:
    expected = GOOGLE_SITE_VERIFICATION_HTML_FILE.strip()
    if not expected or "/" in expected:
        return

    @router.get(f"/{expected}", response_class=HTMLResponse, include_in_schema=False)
    def google_site_verification_file() -> HTMLResponse:
        body = GOOGLE_SITE_VERIFICATION_HTML_BODY.strip()
        if not body:
            body = f"google-site-verification: {expected}"
        return HTMLResponse(content=body, media_type="text/html; charset=utf-8")


_register_google_verification_route()
