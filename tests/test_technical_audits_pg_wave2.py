"""Wave 2: technical audits PG dual-write, isolation, concurrency, count parity."""

from __future__ import annotations

import threading
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def audit_pg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolated SQLite for PG path + temp JSON file."""
    db_path = tmp_path / "audits.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Minimal users table for FK
    from sqlalchemy import Integer, MetaData, String, Table, Column

    meta = MetaData()
    Table(
        "users",
        meta,
        Column("id", Integer, primary_key=True),
        Column("email", String(200)),
    )
    meta.create_all(engine)
    with engine.begin() as conn:
        conn.execute(meta.tables["users"].insert(), [{"id": 1, "email": "a@t"}, {"id": 2, "email": "b@t"}])

    import app.models.technical_audit  # noqa: F401
    from app.db import Base
    from app.models.technical_audit import TechnicalAudit

    # Register related mappers so configure() does not fail if knowledge was imported elsewhere.
    try:
        import app.models.seo  # noqa: F401
        import app.models.knowledge  # noqa: F401
        import app.models.user  # noqa: F401
    except Exception:
        pass

    Base.metadata.create_all(bind=engine, tables=[TechnicalAudit.__table__])
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_technical_audits_user_idem "
            "ON technical_audits (user_id, idempotency_key) "
            "WHERE idempotency_key IS NOT NULL AND idempotency_key != ''"
        )

    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr("app.db.engine", engine)
    monkeypatch.setattr("app.db.SessionLocal", Session)
    monkeypatch.setattr("app.services.technical_audit_pg.SessionLocal", Session)
    monkeypatch.setenv("TECHNICAL_AUDITS_PG", "1")
    monkeypatch.setenv("TECHNICAL_AUDITS_PG_READ", "1")
    monkeypatch.setenv("TECHNICAL_AUDITS_JSON_WRITE", "1")
    monkeypatch.setattr(
        "app.services.audit_store.AUDIT_FILE",
        tmp_path / "technical_audits.json",
    )
    return tmp_path


def test_tenant_isolation_pg(audit_pg):
    from app.services.audit_store import get_audit_for_user, list_audits, save_technical_audit

    payload = {
        "domain": "a.test",
        "pages_scanned": 1,
        "issues": [],
        "technical_summary": {"health_score": 10},
    }
    id_a = save_technical_audit(user_id=1, source_url="https://a.test", result=payload)
    id_b = save_technical_audit(
        user_id=2,
        source_url="https://b.test",
        result={**payload, "domain": "b.test"},
    )
    assert get_audit_for_user(id_a, 1) is not None
    assert get_audit_for_user(id_a, 2) is None
    assert get_audit_for_user(id_b, 2) is not None
    assert get_audit_for_user(id_b, 1) is None
    assert all(r["id"] != id_b for r in list_audits(10, user_id=1))
    assert all(r["id"] != id_a for r in list_audits(10, user_id=2))


def test_dual_write_json_and_pg(audit_pg):
    from app.services.audit_store import AUDIT_FILE, save_technical_audit
    from app.services.json_atomic import read_json_list
    from app.services.technical_audit_pg import count_audits_pg, get_audit_pg

    aid = save_technical_audit(
        user_id=1,
        source_url="https://dual.test",
        result={"domain": "dual.test", "pages_scanned": 2, "issues": [], "technical_summary": {}},
        idempotency_key="idem-dual-1",
    )
    assert get_audit_pg(aid, 1) is not None
    assert count_audits_pg() == 1
    js = read_json_list(AUDIT_FILE)
    assert any(str(r.get("id")) == aid for r in js)


def test_idempotent_save_no_duplicate(audit_pg):
    from app.services.audit_store import save_technical_audit
    from app.services.technical_audit_pg import count_audits_pg

    key = "idem-same"
    payload = {"domain": "i.test", "pages_scanned": 1, "issues": [], "technical_summary": {}}
    a1 = save_technical_audit(user_id=1, source_url="https://i.test", result=payload, idempotency_key=key)
    a2 = save_technical_audit(user_id=1, source_url="https://i.test", result=payload, idempotency_key=key)
    assert a1 == a2
    assert count_audits_pg() == 1


def test_concurrent_writes_unique_ids(audit_pg, monkeypatch):
    monkeypatch.setenv("TECHNICAL_AUDITS_JSON_WRITE", "0")
    from app.services.audit_store import save_technical_audit
    from app.services.technical_audit_pg import count_audits_pg

    ids: list[str] = []
    lock = threading.Lock()
    errors: list[str] = []

    def worker(n: int):
        try:
            aid = save_technical_audit(
                user_id=1,
                source_url=f"https://c{n}.test",
                result={
                    "domain": f"c{n}.test",
                    "pages_scanned": 1,
                    "issues": [],
                    "technical_summary": {},
                },
                idempotency_key=f"conc-{n}-{uuid.uuid4().hex[:6]}",
            )
            with lock:
                ids.append(aid)
        except Exception as exc:
            with lock:
                errors.append(str(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    assert len(ids) == 8
    assert len(set(ids)) == 8
    assert count_audits_pg() == 8


def test_migrate_idempotent(audit_pg, tmp_path):
    from app.migrations.migrate_technical_audits_json_to_pg import migrate_json_to_pg
    from app.services.json_atomic import write_json_list
    from app.services.technical_audit_pg import count_audits_pg

    path = tmp_path / "legacy.json"
    rows = [
        {
            "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeee1",
            "user_id": 1,
            "at": "2026-01-01T00:00:00+00:00",
            "source_url": "https://leg.test",
            "domain": "leg.test",
            "pages_scanned": 1,
            "issues": [],
            "technical_summary": {},
        },
        {
            "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeee2",
            "user_id": 2,
            "at": "2026-01-02T00:00:00+00:00",
            "source_url": "https://leg2.test",
            "domain": "leg2.test",
            "pages_scanned": 1,
            "issues": [{"type": "x"}],
            "technical_summary": {},
        },
    ]
    write_json_list(path, rows)
    r1 = migrate_json_to_pg(json_path=path)
    assert r1["inserted"] == 2
    assert r1["pg_count"] == 2
    r2 = migrate_json_to_pg(json_path=path)
    assert r2["inserted"] == 0
    assert r2["updated"] == 2
    assert count_audits_pg() == 2
