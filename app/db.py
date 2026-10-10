"""Database engine factory — WAVE 3 pool budget + PgBouncer transaction pooling."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool, QueuePool

_default_sqlite = "sqlite:///./app.db"
DATABASE_URL = (os.getenv("DATABASE_URL") or _default_sqlite).strip()


def _resolve_sqlite_relative_url(url: str) -> str:
    if not url.startswith("sqlite:///"):
        return url
    path_part = url[len("sqlite:///") :]
    if path_part.startswith("/") or (len(path_part) >= 3 and path_part[1:3] == ":/"):
        return url
    base_dir = Path(__file__).resolve().parents[1]
    abs_path = (base_dir / path_part).resolve()
    return "sqlite:///" + abs_path.as_posix()


def use_pgbouncer() -> bool:
    if os.getenv("DB_USE_PGBOUNCER", "0").strip().lower() in ("1", "true", "yes", "on"):
        return True
    url = DATABASE_URL.lower()
    return ":6433/" in url or "pgbouncer" in url


def _process_role() -> str:
    if os.getenv("CELERY_WORKER", "").strip().lower() in ("1", "true", "yes"):
        return "celery"
    if os.getenv("CELERY_BEAT", "").strip().lower() in ("1", "true", "yes"):
        return "beat"
    return "web"


def _pool_size_for_role() -> int:
    role = _process_role()
    if role == "celery":
        return int(os.getenv("DB_POOL_SIZE_WORKER", os.getenv("DB_POOL_SIZE", "2")))
    if role == "beat":
        return int(os.getenv("DB_POOL_SIZE_BEAT", "1"))
    return int(os.getenv("DB_POOL_SIZE_WEB", os.getenv("DB_POOL_SIZE", "3")))


def _max_overflow_for_role() -> int:
    role = _process_role()
    if role == "celery":
        return int(os.getenv("DB_MAX_OVERFLOW_WORKER", os.getenv("DB_MAX_OVERFLOW", "2")))
    if role == "beat":
        return int(os.getenv("DB_MAX_OVERFLOW_BEAT", "1"))
    return int(os.getenv("DB_MAX_OVERFLOW_WEB", os.getenv("DB_MAX_OVERFLOW", "3")))


def _statement_timeout_ms() -> int:
    try:
        return max(1000, int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "30000")))
    except (TypeError, ValueError):
        return 30000


def _pg_connect_args() -> dict:
    app_name = os.getenv("DB_APPLICATION_NAME", "").strip() or f"seoauto_{_process_role()}"
    args: dict = {"application_name": app_name[:63]}
    # PgBouncer transaction mode rejects -c options at connect; use connect event instead.
    if not use_pgbouncer():
        args["options"] = f"-c statement_timeout={_statement_timeout_ms()}"
    return args


def _attach_pg_timeouts(dbapi_connection, _connection_record) -> None:
    try:
        ms = _statement_timeout_ms()
        cur = dbapi_connection.cursor()
        cur.execute(f"SET statement_timeout = {int(ms)}")
        cur.close()
    except Exception:
        pass


def create_db_engine():
    if DATABASE_URL.startswith("sqlite"):
        url = _resolve_sqlite_relative_url(DATABASE_URL)
        eng = create_engine(
            url,
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
        )
        return eng

    connect_args = _pg_connect_args()
    if use_pgbouncer():
        # Transaction pooling: client-side NullPool; PgBouncer owns server connections.
        eng = create_engine(
            DATABASE_URL,
            poolclass=NullPool,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
    else:
        eng = create_engine(
            DATABASE_URL,
            poolclass=QueuePool,
            pool_pre_ping=True,
            pool_size=_pool_size_for_role(),
            max_overflow=_max_overflow_for_role(),
            pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "10")),
            pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "1800")),
            pool_reset_on_return="rollback",
            connect_args=connect_args,
        )
    event.listen(eng, "connect", _attach_pg_timeouts)
    return eng


engine = create_db_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def release_db_before_long_io(db: Session) -> None:
    """End any open transaction so PgBouncer can free the server connection.

    Long external API calls (Google Ads / DataForSEO) must not hold an idle
    transaction — otherwise the backend connection dies and the next SQL
    raises OperationalError (500).
    """
    try:
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


def ensure_db_alive(db: Session) -> None:
    """Ping / reconnect after long I/O. Safe with NullPool + PgBouncer."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError, OperationalError

    def _ping() -> None:
        db.execute(text("SELECT 1"))

    try:
        _ping()
        return
    except (OperationalError, DBAPIError, Exception):
        pass
    try:
        db.rollback()
    except Exception:
        pass
    try:
        conn = db.connection()
        conn.invalidate()
    except Exception:
        pass
    try:
        db.rollback()
    except Exception:
        pass
    _ping()


def connection_budget() -> dict:
    """Documented per-process connection budget (for audits)."""
    role = _process_role()
    if use_pgbouncer():
        return {
            "role": role,
            "pgbouncer": True,
            "client_pool": "NullPool",
            "pgbouncer_default_pool_size": int(os.getenv("PGBOUNCER_DEFAULT_POOL_SIZE", "25")),
        }
    ps = _pool_size_for_role()
    mo = _max_overflow_for_role()
    return {
        "role": role,
        "pgbouncer": False,
        "pool_size": ps,
        "max_overflow": mo,
        "max_per_process": ps + mo,
    }
