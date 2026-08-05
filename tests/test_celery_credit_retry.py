"""Celery keyword research credit: hold across retries; release only on final failure."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db import Base
from app.models.user import User
from app.services.credits import get_available_balance, grant_credits, reserve_credits


@pytest.fixture()
def db(monkeypatch):
    import app.models.credit_ledger  # noqa: F401
    import app.models.credit_ledger_entry  # noqa: F401
    import app.models.credit_reservation  # noqa: F401
    import app.models.plan  # noqa: F401
    import app.models.subscription  # noqa: F401
    import app.models.user  # noqa: F401

    monkeypatch.setenv("CREDITS_ENABLED", "1")
    monkeypatch.setattr(
        "app.services.saas_economics_guard.check_economics_after_burn",
        lambda *a, **k: None,
        raising=False,
    )
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_retry_keeps_reservation_without_redebit(db):
    from app.models.credit_reservation import CreditReservation
    from app.workers import keyword_tasks as kt

    u = User(email=f"c-{uuid.uuid4().hex[:8]}@t.local", password_hash=hash_password("x"), has_password=True)
    db.add(u)
    db.flush()
    grant_credits(db, user_id=u.id, amount=40, reason="t", source_type="admin")
    key = f"celery-idem-{uuid.uuid4().hex}"
    res = reserve_credits(
        db,
        user_id=u.id,
        amount=15,
        feature_code="keyword_research",
        job_id=key,
        idempotency_key=key,
    )
    db.commit()
    bal1 = get_available_balance(db, u.id)
    assert bal1 == 25

    # Simulated mid-retry: no finalize yet — balance & status unchanged
    row = db.get(CreditReservation, res["reservation_id"])
    assert str(row.status) == "reserved"

    # re-reserve same key (worker restart) must not re-debit
    res2 = reserve_credits(
        db,
        user_id=u.id,
        amount=15,
        feature_code="keyword_research",
        job_id=key,
        idempotency_key=key,
    )
    assert int(res2["reservation_id"]) == int(res["reservation_id"])
    assert get_available_balance(db, u.id) == 25

    # Final failure → release once
    SessionLocal = sessionmaker(bind=db.get_bind())
    payload = {"_owner_user_id": u.id, "_credit_reservation_id": res["reservation_id"]}
    with patch("app.db.SessionLocal", SessionLocal):
        kt._finalize_reservation(payload, success=False)
    db.expire_all()
    assert str(db.get(CreditReservation, res["reservation_id"]).status) == "released"
    assert get_available_balance(db, u.id) == 40

    # Second finalization is no-op (no double refund)
    with patch("app.db.SessionLocal", SessionLocal):
        kt._finalize_reservation(payload, success=False)
    assert get_available_balance(db, u.id) == 40


def test_success_commits_without_extra_debit(db):
    from app.models.credit_reservation import CreditReservation
    from app.workers import keyword_tasks as kt

    u = User(email=f"s-{uuid.uuid4().hex[:8]}@t.local", password_hash=hash_password("x"), has_password=True)
    db.add(u)
    db.flush()
    grant_credits(db, user_id=u.id, amount=30, reason="t", source_type="admin")
    key = f"ok-{uuid.uuid4().hex}"
    res = reserve_credits(
        db,
        user_id=u.id,
        amount=10,
        feature_code="keyword_research",
        job_id=key,
        idempotency_key=key,
    )
    db.commit()
    SessionLocal = sessionmaker(bind=db.get_bind())
    payload = {"_owner_user_id": u.id, "_credit_reservation_id": res["reservation_id"]}
    with patch("app.db.SessionLocal", SessionLocal):
        kt._finalize_reservation(payload, success=True)
    db.expire_all()
    assert str(db.get(CreditReservation, res["reservation_id"]).status) == "committed"
    assert get_available_balance(db, u.id) == 20
