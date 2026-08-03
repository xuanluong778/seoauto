#!/usr/bin/env python3
"""Sync SEOAuto billing catalog (product codes, starter display name) without overwriting prices."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / "env.local")

from app.db import SessionLocal
from app.services.seoauto_pricing_catalog import ensure_billing_catalog_sync, get_billing_catalog


def main() -> int:
    db = SessionLocal()
    try:
        stats = ensure_billing_catalog_sync(db)
        db.commit()
        catalog = get_billing_catalog(db)
        print("Billing catalog sync:", json.dumps(stats, ensure_ascii=False))
        print("Products:", len(catalog.get("products") or []))
        print("Credit add-ons:", len(catalog.get("credit_addons") or []))
        print("Article add-ons:", len(catalog.get("article_addons") or []))
        for plan in catalog.get("plans") or []:
            print(
                f"  plan {plan['slug']}: name={plan['name']!r} "
                f"codes={plan.get('product_codes')}"
            )
        return 0
    except Exception as exc:
        db.rollback()
        print("ERROR:", exc, file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
