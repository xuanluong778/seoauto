#!/usr/bin/env python3
"""WAVE 5 — Embedding / duplicate-check validation gates.

Output: docs/baseline/wave5/
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "baseline" / "wave5"
WAVE0 = ROOT / "docs" / "baseline" / "wave0"
KNOWN_FAILURES = WAVE0 / "KNOWN_FAILURES_WAVE0.txt"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_env() -> None:
    for env_path in (ROOT / "env.local", Path("/var/www/seoauto_vn_usr/data/www/shared/env.local")):
        if not env_path.is_file():
            continue
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line or line.strip().startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k and k not in os.environ:
                v = v.strip()
                if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                    v = v[1:-1]
                os.environ[k] = v


def _pytest(target: str) -> dict[str, Any]:
    proc = subprocess.run(
        [str(ROOT / ".venv/bin/pytest"), "-q", "--tb=no", *target.split()],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=300,
        env={
            **os.environ,
            "PYTHONPATH": str(ROOT),
            "EMBEDDING_CELERY_WORKER": "1",
            "DUPLICATE_WP_CORPUS_CACHE": "1",
            "DUPLICATE_WP_ASYNC_FETCH": "1",
        },
    )
    tail = (proc.stdout or "")[-800:]
    return {
        "gate": "PASS" if proc.returncode == 0 else "FAIL",
        "returncode": proc.returncode,
        "tail": tail,
    }


def _count_known_failures() -> int:
    if not KNOWN_FAILURES.is_file():
        return 0
    return sum(1 for line in KNOWN_FAILURES.read_text().splitlines() if line.strip())


def _audit_embedding_memory() -> dict[str, Any]:
    from app.services.embedding_worker_rollout import (
        embedding_celery_enabled,
        uvicorn_may_load_embedding_model,
    )
    from app.services.semantic_embedding import model_load_count

    web_loads = 0
    with mock.patch.dict(os.environ, {"EMBEDDING_CELERY_WORKER": "1"}, clear=False):
        os.environ.pop("CELERY_EMBEDDING_WORKER", None)
        from importlib import reload
        import app.services.embedding_worker_rollout as rollout
        import app.services.semantic_embedding as sem

        reload(rollout)
        reload(sem)
        blocked = not rollout.uvicorn_may_load_embedding_model()
        with mock.patch("app.services.semantic_embedding._embed_sentence_transformers", return_value=None):
            sem.embed_keywords(["test gate keyword"], tenant_scope="gate")
        web_loads = sem.model_load_count()

    ok = embedding_celery_enabled() and blocked and web_loads == 0
    return {
        "gate": "PASS" if ok else "FAIL",
        "embedding_celery_enabled": embedding_celery_enabled(),
        "uvicorn_may_load_model": uvicorn_may_load_embedding_model(),
        "web_model_load_count": web_loads,
    }


def _audit_wp_fetch() -> dict[str, Any]:
    import uuid

    from app.services.duplicate_wp_corpus_cache import reset_metrics, metrics_snapshot, get_live_site_articles_cached
    from app.services.content_ai_duplicate_detection import ExistingArticleRef

    reset_metrics()
    site = f"https://gate-mock-{uuid.uuid4().hex[:8]}.test"
    refs = [
        ExistingArticleRef(keyword="gate kw", title="Gate", url=f"{site}/a", source="published")
    ]

    with mock.patch(
        "app.services.content_ai_duplicate_detection._collect_live_site_articles",
        return_value=refs,
    ):
        get_live_site_articles_cached(user_id=999001, target_website=site, search_keywords=["gate kw"])
        get_live_site_articles_cached(user_id=999001, target_website=site, search_keywords=["gate kw"])

    m = metrics_snapshot()
    ok = m["wp_fetch_count"] == 1 and m["wp_cache_hit"] >= 1
    return {"gate": "PASS" if ok else "FAIL", **m}


def _load_concurrent(n: int) -> dict[str, Any]:
    from app.services.content_ai_duplicate_detection import check_keywords_for_duplicates, ExistingArticleRef

    corpus = [ExistingArticleRef(keyword=f"load kw {i}", title=f"T {i}") for i in range(30)]

    def _one(_):
        with mock.patch(
            "app.services.content_ai_duplicate_detection.collect_existing_articles",
            return_value=corpus,
        ), mock.patch(
            "app.services.duplicate_wp_corpus_cache.get_live_site_articles_cached",
            return_value=[],
        ), mock.patch(
            "app.services.content_ai_duplicate_detection.embed_keywords",
            return_value={},
        ):
            t0 = time.perf_counter()
            rows = check_keywords_for_duplicates(["load kw 0", "unique"], user_id=7, db=None)
            return time.perf_counter() - t0, rows

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=min(n, 20)) as pool:
        out = list(pool.map(_one, range(n)))
    elapsed = time.perf_counter() - t0
    latencies = [x[0] for x in out]
    p95 = sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)] if latencies else 0
    ok = all(len(x[1]) == 2 for x in out)
    return {
        "gate": "PASS" if ok else "FAIL",
        "concurrency": n,
        "total_elapsed_s": round(elapsed, 3),
        "p95_latency_ms": round(p95 * 1000, 1),
        "requests": n,
    }


def main() -> int:
    _load_env()
    os.environ["EMBEDDING_CELERY_WORKER"] = "1"
    os.environ["DUPLICATE_WP_CORPUS_CACHE"] = "1"
    os.environ["DUPLICATE_WP_ASYNC_FETCH"] = "1"
    OUT.mkdir(parents=True, exist_ok=True)

    from scripts.wave5_embedding_production import (
        audit_async_refresh_nonblocking,
        audit_embedding_queue_wait,
        audit_large_corpus,
        audit_live_wp_corpus,
        audit_production_flags,
        audit_rollback,
        audit_wp_429_500_recovery,
        audit_wp_timeout_recovery,
        collect_system_metrics,
    )

    report: dict[str, Any] = {
        "wave": 5,
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "gates": {},
        "fixes": [
            "EMBEDDING_CELERY_WORKER=1 — ST only in seoauto-worker-embedding",
            "Tenant-scoped emb:v2:{tenant}:{content_hash} cache",
            "DUPLICATE_WP_CORPUS_CACHE=1 — Redis corpus per user/site/keywords",
            "duplicate.sync_wp_corpus background refresh (async)",
            "invalidate_wp_corpus_for_site on publish success",
        ],
    }

    wave5_tests = _pytest("tests/test_wave5_embedding_duplicate.py")
    dup_regression = _pytest("tests/test_content_ai_duplicate_detection.py")
    embed_mem = _audit_embedding_memory()

    prod_flags = audit_production_flags()
    live_wp = audit_live_wp_corpus()
    large_corpus = audit_large_corpus()
    wp_timeout = audit_wp_timeout_recovery()
    wp_errors = audit_wp_429_500_recovery()
    async_nb = audit_async_refresh_nonblocking()
    rollback = audit_rollback()
    embed_queue = audit_embedding_queue_wait()
    system_metrics = collect_system_metrics()
    wp_fetch = _audit_wp_fetch()

    report["wave5_tests"] = wave5_tests
    report["duplicate_regression"] = dup_regression
    report["embedding_memory"] = embed_mem
    report["wp_fetch_audit"] = wp_fetch

    load_1 = _load_concurrent(1)
    load_10 = _load_concurrent(10)
    load_50 = _load_concurrent(50)
    load_100 = _load_concurrent(100)
    report["load"] = {"1": load_1, "10": load_10, "50": load_50, "100": load_100}

    from app.services.embedding_cache import metrics_snapshot as emb_metrics

    report["embedding_cache_metrics"] = emb_metrics()

    report["production_flags"] = prod_flags
    report["live_wp"] = live_wp
    report["large_corpus"] = large_corpus
    report["wp_timeout_recovery"] = wp_timeout
    report["wp_error_recovery"] = wp_errors
    report["async_nonblocking"] = async_nb
    report["rollback"] = rollback
    report["embedding_queue"] = embed_queue
    report["system_metrics"] = system_metrics

    report["gates"]["DUPLICATE_CHECK"] = wave5_tests["gate"]
    report["gates"]["EMBEDDING_MEMORY"] = embed_mem["gate"]
    report["gates"]["EMBEDDING_CACHE"] = wave5_tests["gate"]
    report["gates"]["WP_FETCH"] = wp_fetch["gate"]
    report["gates"]["WP_INCREMENTAL_SYNC"] = wave5_tests["gate"]
    report["gates"]["ASYNC_WP_FETCH"] = wave5_tests["gate"]
    report["gates"]["CACHE_INVALIDATION"] = wave5_tests["gate"]
    report["gates"]["TENANT_ISOLATION"] = wave5_tests["gate"]
    report["gates"]["DUPLICATE_OUTPUT_REGRESSION"] = dup_regression["gate"]
    report["gates"]["LOAD_100"] = load_100["gate"]
    report["gates"]["LIVE_WP_CORPUS"] = live_wp["gate"]
    report["gates"]["COLD_CACHE"] = live_wp.get("cold_cache_gate", "FAIL")
    report["gates"]["WARM_CACHE"] = live_wp.get("warm_cache_gate", "FAIL")
    report["gates"]["LARGE_CORPUS"] = large_corpus["gate"]
    report["gates"]["WP_TIMEOUT_RECOVERY"] = wp_timeout["gate"]
    report["gates"]["WP_429_500_RECOVERY"] = wp_errors["gate"]
    report["gates"]["PRODUCTION_FLAGS"] = prod_flags["gate"]
    report["gates"]["ROLLBACK"] = rollback["gate"]
    if live_wp.get("tenant_gate") != "PASS":
        report["gates"]["TENANT_ISOLATION"] = "FAIL"
    if async_nb["gate"] != "PASS":
        report["gates"]["ASYNC_WP_FETCH"] = "FAIL"

    known_now = _count_known_failures()
    report["known_failures_baseline"] = known_now
    baseline_path = OUT / "known_failures_baseline.txt"
    if baseline_path.is_file():
        baseline = int(baseline_path.read_text().strip() or "0")
    else:
        baseline = known_now
        baseline_path.write_text(str(baseline), encoding="utf-8")
    report["gates"]["KNOWN_FAILURES_NOT_INCREASED"] = (
        "PASS" if known_now <= baseline else "FAIL"
    )

    failed = [k for k, v in report["gates"].items() if v != "PASS"]
    report["failed_gates"] = failed
    report["WAVE_5_EMBEDDING_DUPLICATE"] = "FULL PASS" if not failed else "FAIL"

    (OUT / "wave5_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    readme = f"""# WAVE 5 — Embedding / Duplicate Check

**Result:** `WAVE_5_EMBEDDING_DUPLICATE = {report["WAVE_5_EMBEDDING_DUPLICATE"]}`
**Snapshot:** {report["snapshot_at"]}

## Architecture

- Uvicorn: duplicate-check API only; no sentence-transformers load when `EMBEDDING_CELERY_WORKER=1`
- `seoauto-worker-embedding`: `embedding.embed_keywords` + `duplicate.sync_wp_corpus`
- Cache: `emb:v2:{{tenant}}:{{content_hash}}` + `dup:wp:{{user}}:{{site}}:{{kw_sig}}`

## Gates

"""
    for gate, status in sorted(report["gates"].items()):
        readme += f"- {gate}: **{status}**\n"
    readme += f"""
## Load test

- 1 concurrent: {load_1.get("p95_latency_ms")}ms p95
- 10 concurrent: {load_10.get("p95_latency_ms")}ms p95
- 50 concurrent: {load_50.get("p95_latency_ms")}ms p95
- 100 concurrent: {load_100.get("p95_latency_ms")}ms p95

## WP fetch (mock audit)

- fetch_count (audit): {wp_fetch.get("wp_fetch_count")}
- cache_hit: {wp_fetch.get("wp_cache_hit")}

## Live WordPress

- Site: {live_wp.get("site")}
- Cold latency: {live_wp.get("cold_latency_ms")}ms
- Warm p95: {live_wp.get("warm_p95_ms")}ms
- Large corpus ({large_corpus.get("keyword_count")} kw): {large_corpus.get("corpus_count")} refs in {large_corpus.get("latency_ms")}ms

## System

- Redis: {system_metrics.get("used_memory_human")}
- Embedding queue depth: {system_metrics.get("embedding_queue_depth")}
- Embedding p95 wait: {embed_queue.get("p95_ms")}ms
"""
    (OUT / "README.md").write_text(readme, encoding="utf-8")

    print(json.dumps({"WAVE_5_EMBEDDING_DUPLICATE": report["WAVE_5_EMBEDDING_DUPLICATE"], "gates": report["gates"]}, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
