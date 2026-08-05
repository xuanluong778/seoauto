#!/usr/bin/env python3
"""Run SePay / payment reconciliation (no bank calls)."""

from __future__ import annotations

import argparse
import json
import logging
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile SePay payments vs plan/ledger")
    parser.add_argument("--repair", action="store_true", help="Attempt reactivation of paid-but-not-activated orders")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON report")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from app.services.payment_reconciliation_service import run_payment_reconciliation_job

    report = run_payment_reconciliation_job(try_repair=bool(args.repair))
    if args.pretty:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        print(json.dumps(report, ensure_ascii=False, default=str))
    issues = (
        len(report.get("paid_without_plan") or [])
        + len(report.get("activated_without_ledger") or [])
        + len(report.get("webhook_anomalies") or [])
    )
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
