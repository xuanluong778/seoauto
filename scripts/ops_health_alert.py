#!/usr/bin/env python3
"""Poll /metrics and emit ops alerts (cron-friendly, WAVE 9).

Usage:
  python scripts/ops_health_alert.py
  python scripts/ops_health_alert.py --simulate   # run simulate_alert_test only

Env:
  WAVE9_BASE_URL — default http://127.0.0.1:8899
  INTERNAL_CRON_TOKEN — required when not localhost
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SHARED_ENV = Path("/var/www/seoauto_vn_usr/data/www/shared/env.local")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_env() -> None:
    for env_path in (ROOT / "env.local", SHARED_ENV):
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


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(description="SEOAuto ops health alert poller")
    parser.add_argument("--simulate", action="store_true", help="Run in-process alert simulation")
    parser.add_argument("--base-url", default=os.getenv("WAVE9_BASE_URL", "http://127.0.0.1:8899"))
    args = parser.parse_args()

    if args.simulate:
        from app.services.ops_alerting import simulate_alert_test

        result = simulate_alert_test()
        print(json.dumps(result, indent=2))
        return 0 if result.get("first_alert_count", 0) > 0 else 1

    base = args.base_url.rstrip("/")
    headers: dict[str, str] = {}
    token = (os.getenv("INTERNAL_CRON_TOKEN") or "").strip()
    if token:
        headers["X-Internal-Token"] = token

    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(f"{base}/metrics", headers=headers)
        if resp.status_code != 200:
            print(json.dumps({"error": "metrics_unavailable", "status": resp.status_code}))
            return 1
        body = resp.json()
        alerts = body.get("alerts") or []
        recovery = body.get("alert_recovery") or {}
        out = {
            "ts": body.get("ts"),
            "alert_count": len(alerts),
            "alerts": alerts,
            "recovery": recovery,
        }
        print(json.dumps(out, indent=2))
        return 1 if alerts else 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)[:300]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
