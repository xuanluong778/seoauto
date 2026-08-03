"""Ghi log debug audit (HTML thô / render / parse) khi bật AUDIT_DEBUG_DIR."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)


def _slug(s: str) -> str:
    s = re.sub(r"[^\w\-]+", "_", (s or "")[:120], flags=re.UNICODE)
    return s.strip("_") or "page"


class AuditDebugSession:
    def __init__(self, base_dir: str | None = None) -> None:
        raw = (base_dir or os.getenv("AUDIT_DEBUG_DIR") or "").strip()
        self.enabled = bool(raw)
        self.root = Path(raw) if self.enabled else None
        self.run_dir: Path | None = None
        if self.enabled and self.root is not None:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            self.run_dir = self.root / ts
            try:
                self.run_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                _LOGGER.warning("AUDIT_DEBUG_DIR không tạo được: %s", exc)
                self.enabled = False
                self.run_dir = None

    def log_page(
        self,
        url: str,
        *,
        rendered_html: str,
        parsed: dict[str, Any],
        raw_response_headers: dict[str, Any] | None = None,
        crawl_record: dict[str, Any] | None = None,
        search_behavior: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled or not self.run_dir:
            return
        sub = _slug(url)
        d = self.run_dir / sub
        cr = crawl_record or {}
        try:
            d.mkdir(parents=True, exist_ok=True)
            (d / "rendered.html").write_text(rendered_html or "", encoding="utf-8", errors="replace")
            (d / "parsed.json").write_text(
                json.dumps(parsed, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if raw_response_headers:
                (d / "response_headers.json").write_text(
                    json.dumps(raw_response_headers, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            raw_html = cr.get("raw_html")
            if isinstance(raw_html, str) and raw_html.strip():
                (d / "raw.html").write_text(raw_html, encoding="utf-8", errors="replace")
            raw_http = {
                k: cr[k]
                for k in (
                    "raw_http_status",
                    "raw_redirect_history",
                    "raw_response_headers",
                    "raw_fetch_error",
                )
                if k in cr
            }
            if raw_http:
                (d / "raw_http.json").write_text(
                    json.dumps(raw_http, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            if cr.get("raw_vs_rendered") is not None:
                (d / "raw_vs_rendered.json").write_text(
                    json.dumps(cr.get("raw_vs_rendered"), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            if cr.get("canonical_resolution") is not None:
                (d / "canonical.json").write_text(
                    json.dumps(cr.get("canonical_resolution"), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            if cr.get("indexability") is not None:
                (d / "indexability.json").write_text(
                    json.dumps(cr.get("indexability"), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            if cr.get("seo_signals") is not None:
                seo_blob = {
                    "seo_signals": cr.get("seo_signals"),
                    "js_seo_risk_score": cr.get("js_seo_risk_score"),
                    "js_seo_risk_level": cr.get("js_seo_risk_level"),
                    "cloaking_risk": cr.get("cloaking_risk"),
                    "cloaking_reason": cr.get("cloaking_reason"),
                }
                (d / "seo_signals.json").write_text(
                    json.dumps(seo_blob, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            if search_behavior:
                (d / "search_behavior.json").write_text(
                    json.dumps(search_behavior, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        except OSError as exc:
            _LOGGER.debug("audit debug write failed: %s", exc)
