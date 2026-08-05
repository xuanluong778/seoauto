#!/usr/bin/env python3
"""Real PostgreSQL concurrent overdraw test for credit reserve (production DATABASE_URL)."""

from __future__ import annotations

import os
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

# ensure app root on path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    from sqlalchemy import text

    from app.core.security import hash_password
    from app.db import SessionLocal, engine
    import importlib
    import pkgutil
    import app.models as _am
    for _m in pkgutil.walk_packages(_am.__path__, _am.__name__ + "."):
        try:
            importlib.import_module(_m.name)
        except Exception:
            pass
    from app.models.user import User
    from app.services.credits import get_available_balance, grant_credits, reserve_credits
    from fastapi import HTTPException

    if engine.dialect.name != "postgresql":
        print("FAIL: DATABASE_URL is not PostgreSQL")
        return 2

    email = f"conc-test-{uuid.uuid4().hex[:10]}@seoauto.local"
    starting = 50
    cost = 30
    workers = 8

    db = SessionLocal()
    try:
        user = User(email=email, password_hash=hash_password("x"), has_password=True)
        db.add(user)
        db.flush()
        grant_credits(
            db,
            user_id=user.id,
            amount=starting,
            reason="pg_concurrent_test_grant",
            note="test only",
            source_type="admin",
        )
        db.commit()
        user_id = int(user.id)
        bal_before = get_available_balance(db, user_id)

        res_before = db.execute(
            text("SELECT count(*) FROM credit_reservations WHERE user_id = :u"),
            {"u": user_id},
        ).scalar()
        debits_before = db.execute(
            text(
                "SELECT coalesce(sum(abs(delta)),0) FROM credit_ledgers "
                "WHERE user_id = :u AND delta < 0"
            ),
            {"u": user_id},
        ).scalar()
    finally:
        db.close()

    print("=== BEFORE ===")
    print(f"user_id={user_id} email={email}")
    print(f"balance={bal_before}")
    print(f"reservations_count={res_before}")
    print(f"debit_abs_sum={debits_before}")

    results: list[str] = []
    lock = threading.Lock()

    def worker(i: int) -> str:
        s = SessionLocal()
        try:
            key = f"pg-conc-{user_id}-{i}-{uuid.uuid4().hex[:8]}"
            try:
                reserve_credits(
                    s,
                    user_id=user_id,
                    amount=cost,
                    feature_code="technical_audit",
                    job_id=f"j-{i}",
                    idempotency_key=key,
                )
                s.commit()
                return "ok"
            except HTTPException as exc:
                s.rollback()
                return f"http-{exc.status_code}"
            except Exception as exc:  # noqa: BLE001
                s.rollback()
                return f"err:{type(exc).__name__}"
        finally:
            s.close()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(worker, i) for i in range(workers)]
        for f in as_completed(futs):
            with lock:
                results.append(f.result())

    ok_n = sum(1 for r in results if r == "ok")
    fail_n = len(results) - ok_n

    db = SessionLocal()
    try:
        bal_after = get_available_balance(db, user_id)
        res_rows = db.execute(
            text(
                "SELECT id, amount, status, idempotency_key FROM credit_reservations "
                "WHERE user_id = :u ORDER BY id"
            ),
            {"u": user_id},
        ).fetchall()
        debits_after = db.execute(
            text(
                "SELECT coalesce(sum(abs(delta)),0) FROM credit_ledgers "
                "WHERE user_id = :u AND delta < 0"
            ),
            {"u": user_id},
        ).scalar()
        # cleanup test user buckets/ledgers optional: mark note
        print("=== AFTER ===")
        print(f"balance={bal_after}")
        print(f"reservations={[dict(id=r[0], amount=r[1], status=r[2]) for r in res_rows]}")
        print(f"debit_abs_sum={debits_after}")
        print(f"results={results}")
        print(f"ok={ok_n} fail={fail_n}")
        print(f"expected_balance={starting - cost * ok_n}")

        passed = (
            ok_n == 1
            and bal_after == starting - cost
            and bal_after >= 0
            and int(debits_after) >= cost
        )
        print("VERDICT", "PASS" if passed else "FAIL")
        return 0 if passed else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
