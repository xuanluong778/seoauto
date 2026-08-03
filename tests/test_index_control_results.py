"""Tests for Index Control tab Kết quả (store logic)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.index_control_results_store import (
    _batch_row,
    _check_ui_status,
    _submit_ui_status,
    safe_percent,
)


def test_safe_percent_no_nan():
    assert safe_percent(0, 0) == 0
    assert safe_percent(20, 35) == 57
    assert safe_percent(35, 35) == 100


def test_submit_ui_status_mapping():
    assert _submit_ui_status("success", 35, 35) == "completed"
    assert _submit_ui_status("failed", 0, 35) == "error"
    assert _submit_ui_status("partial", 10, 35) == "processing"


def test_check_ui_status_not_checked():
    code, label = _check_ui_status(
        submit_status="success",
        checked_count=0,
        total_links=35,
        dripfeed_days=1,
        created_at=datetime.now(timezone.utc),
    )
    assert code == "not_checked"
    assert label == "Chưa check"


def test_check_ui_status_processing_days_left():
    created = datetime.now(timezone.utc) - timedelta(hours=2)
    code, label = _check_ui_status(
        submit_status="success",
        checked_count=5,
        total_links=35,
        dripfeed_days=5,
        created_at=created,
    )
    assert code == "processing"
    assert "ngày còn lại" in label


def test_batch_row_index_stats():
    now = datetime.now(timezone.utc)
    parent = SimpleNamespace(
        id=1,
        project_name="Entity test batch",
        url_count=2,
        submit_status="success",
        domain="example.com",
        note=None,
        created_at=now,
    )
    logs = [
        SimpleNamespace(
            send_status="sent",
            payload_json='{"indexed":"Index","index_status":"indexed"}',
        ),
        SimpleNamespace(
            send_status="sent",
            payload_json='{"indexed":"No","index_status":"not_found","message":"Not in Google"}',
        ),
    ]
    row = _batch_row(parent, logs=logs)
    assert row["total_links"] == 2
    assert row["indexed_count"] == 1
    assert row["indexed_percent"] == 50
    assert row["submitted_count"] == 2
    assert row["submit_status"] == "completed"
    assert row["submit_status_label"] == "Hoàn tất"


def test_batch_row_failed_submit():
    now = datetime.now(timezone.utc)
    parent = SimpleNamespace(
        id=2,
        project_name="Failed batch",
        url_count=3,
        submit_status="failed",
        domain="example.com",
        note=None,
        created_at=now,
    )
    row = _batch_row(parent, logs=[])
    assert row["submit_status"] == "error"
    assert row["check_status"] == "error"
