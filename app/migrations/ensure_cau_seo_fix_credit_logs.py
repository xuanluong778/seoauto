"""Create cau_seo_fix_credit_logs table."""

from __future__ import annotations

from app.db import Base, engine
from sqlalchemy import inspect


def ensure_cau_seo_fix_credit_logs_table() -> bool:
    from app.models.cau_seo_fix_credit_log import CauSeoFixCreditLog  # noqa: F401

    _ = CauSeoFixCreditLog
    Base.metadata.create_all(bind=engine, tables=[CauSeoFixCreditLog.__table__])
    insp = inspect(engine)
    return "cau_seo_fix_credit_logs" in insp.get_table_names()


def ensure_cau_seo_fix_credit_logs() -> dict[str, object]:
    created = ensure_cau_seo_fix_credit_logs_table()
    return {"cau_seo_fix_credit_logs_table": created}
