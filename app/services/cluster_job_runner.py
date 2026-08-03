"""Run keyword cluster jobs (shared by inline handler + keyword_cluster_worker.py)."""

from __future__ import annotations

import os
import traceback
from typing import Any, Callable


def run_cluster_job(
    job_id: str,
    payload: dict[str, Any],
    *,
    progress_hook: Callable[[int, str], None] | None = None,
) -> None:
    from app.services.job_store import fail_job, finish_job, update_job
    from app.services.keyword_cluster_pipeline import build_keyword_cluster_api_response

    keywords = payload.get("keywords") or []
    fetch_serp = bool(payload.get("fetch_serp"))
    if os.getenv("BENCH_FAST", "0").lower() in ("1", "true", "yes"):
        fetch_serp = False

    def hook(p: int, msg: str) -> None:
        if progress_hook:
            progress_hook(p, msg)
        else:
            update_job(job_id, progress=int(p), message=str(msg))

    try:
        update_job(job_id, state="RUNNING", progress=1, message="Đang gom nhóm…")
        res = build_keyword_cluster_api_response(
            keywords,
            fetch_serp=fetch_serp,
            brand_host_hint=payload.get("brand_host_hint"),
            serp_country=payload.get("serp_country"),
            serp_language=payload.get("serp_language"),
            serp_device=payload.get("serp_device"),
            cluster_strictness=payload.get("cluster_strictness"),
            progress_hook=hook,
        )
        finish_job(job_id, result=res)
    except Exception:
        fail_job(job_id, error=traceback.format_exc())
