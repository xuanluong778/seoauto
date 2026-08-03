"""Tests for SePay webhook transaction storage."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.migrations.ensure_sepay_payment_transactions import ensure_sepay_payment_transactions_table
from app.services.sepay_webhook_service import (
    extract_order_code_from_content,
    parse_sepay_webhook_payload,
    record_sepay_webhook,
)


@pytest.fixture()
def db():
    import app.models.sepay_payment_transaction  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    ensure_sepay_payment_transactions_table()
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_parse_sepay_webhook_payload():
    payload = {
        "id": "SEPAY-12345",
        "accountNumber": "7982468",
        "transferAmount": 699000,
        "transferType": "in",
        "content": "CK SEOA2025061799 PRO",
    }
    parsed = parse_sepay_webhook_payload(payload)
    assert parsed["sepay_transaction_id"] == "SEPAY-12345"
    assert parsed["account_number"] == "7982468"
    assert parsed["transfer_amount"] == 699000
    assert parsed["transfer_type"] == "in"
    assert parsed["order_code"] == "SEOA2025061799"
    assert json.loads(parsed["raw_payload"])["id"] == "SEPAY-12345"


def test_extract_order_code_from_content():
    assert extract_order_code_from_content("Thanh toan SEOA20250617123") == "SEOA20250617123"
    assert extract_order_code_from_content("no code") is None
    assert extract_order_code_from_content("CK SEOA 2026-0708-39 ACB") == "SEOA2026070839"
    assert extract_order_code_from_content("xxxSEOA2026070839yyy") == "SEOA2026070839"
    assert extract_order_code_from_content("ma: seoa2026070839") == "SEOA2026070839"


def test_record_sepay_webhook_idempotent(db):
    payload = {
        "id": "TX-001",
        "transferAmount": 100000,
        "content": "SEOA202506171",
    }
    row1, created1, status1 = record_sepay_webhook(db, payload)
    db.commit()
    assert created1 is True
    assert status1 == "created"
    assert row1 is not None
    assert row1.sepay_transaction_id == "TX-001"

    row2, created2, status2 = record_sepay_webhook(db, payload)
    assert created2 is False
    assert status2 == "duplicate"
    assert row2 is not None
    assert row2.id == row1.id


def test_record_sepay_webhook_missing_id(db):
    row, created, status = record_sepay_webhook(db, {"transferAmount": 1})
    assert row is None
    assert created is False
    assert status == "missing_transaction_id"
