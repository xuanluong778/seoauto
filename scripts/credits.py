"""
Per-user credits: optional enforcement via CREDITS_ENABLED=1.

Costs are integers (điểm credit). Tune with env vars.
"""

from __future__ import annotations

import json
import os

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.credit_ledger import CreditLedger
from app.models.user import User


def credits_enforced() -> bool:
    return os.getenv("CREDITS_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")


_DEFAULT_CREDIT_PACKAGES: list[dict[str, str | int | None]] = [
    {
        "id": "trial",
        "name": "Dùng thử",
        "credits": 200,
        "description": "Mức gần với credit đăng ký (SIGNUP_CREDIT_BONUS). Thử keyword research & clustering.",
        "price_hint": "Theo tài khoản mới",
    },
    {
        "id": "lite",
        "name": "Lite",
        "credits": 2000,
        "description": "Ví dụ ~400 lần research nếu CREDIT_COST_RESEARCH_RUN=5.",
        "price_hint": "Liên hệ admin",
    },
    {
        "id": "pro",
        "name": "Pro",
        "credits": 10000,
        "description": "Phù hợp agency / volume cao.",
        "price_hint": "Liên hệ admin",
    },
]


def public_credit_packages() -> list[dict[str, str | int | None]]:
    """
    Danh sách gói hiển thị cho khách (cấu hình qua CREDIT_PACKAGES_JSON hoặc mặc định).
    Mỗi phần tử: id, name, credits, description?, price_hint?
    """
    raw = (os.getenv("CREDIT_PACKAGES_JSON") or "").strip()
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list) and data:
            out: list[dict[str, str | int | None]] = []
            for i, row in enumerate(data):
                if not isinstance(row, dict):
                    continue
                pid = str(row.get("id") or f"pkg{i}").strip()[:64]
                name = str(row.get("name") or pid).strip()[:120]
                if not pid or not name:
                    continue
                try:
                    cred = int(row.get("credits", 0))
                except (TypeError, ValueError):
                    cred = 0
                cred = max(0, cred)
                desc = str(row.get("description") or "").strip()[:2000]
                ph = row.get("price_hint")
                hint = str(ph).strip()[:200] if ph is not None and str(ph).strip() else None
                out.append({"id": pid, "name": name, "credits": cred, "description": desc, "price_hint": hint})
            if out:
                return out
    return [dict(x) for x in _DEFAULT_CREDIT_PACKAGES]


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


def cost_research_run() -> int:
    return max(0, _int_env("CREDIT_COST_RESEARCH_RUN", 5))


def cost_volume_per_keyword() -> int:
    return max(0, _int_env("CREDIT_COST_VOLUME_PER_KEYWORD", 1))


def volume_batch_charge(keyword_count: int) -> int:
    per = cost_volume_per_keyword()
    if per <= 0:
        return 0
    raw = max(0, int(keyword_count)) * per
    cap = _int_env("CREDIT_VOLUME_BATCH_MAX_CHARGE", 300)
    if cap <= 0:
        return raw
    return min(raw, cap)


def cost_cluster_sync() -> int:
    return max(0, _int_env("CREDIT_COST_CLUSTER_SYNC", 3))


def cost_cluster_async() -> int:
    return max(0, _int_env("CREDIT_COST_CLUSTER_ASYNC", 2))


def cost_cluster_save() -> int:
    return max(0, _int_env("CREDIT_COST_CLUSTER_SAVE", 2))


def cost_import_excel() -> int:
    return max(0, _int_env("CREDIT_COST_IMPORT_EXCEL", 1))


def cost_analyze_project() -> int:
    return max(0, _int_env("CREDIT_COST_ANALYZE_PROJECT", 10))


def cost_technical_analyze() -> int:
    return max(0, _int_env("CREDIT_COST_TECHNICAL_ANALYZE", 5))


def cost_url_seo_scoreboard() -> int:
    return max(0, _int_env("CREDIT_COST_URL_SEO_SCOREBOARD", 3))


def signup_bonus() -> int:
    return max(0, _int_env("SIGNUP_CREDIT_BONUS", 0))


def admin_grant_secret() -> str:
    return (os.getenv("CREDITS_ADMIN_SECRET") or "").strip()


def _user_query_for_update(db: Session, user_id: int):
    q = db.query(User).filter(User.id == user_id)
    if db.bind is not None and db.bind.dialect.name != "sqlite":
        q = q.with_for_update()
    return q


def consume_credits(
    db: Session,
    *,
    user_id: int,
    amount: int,
    reason: str,
    note: str | None = None,
) -> int:
    """
    Atomically subtract credits. Caller must commit.
    Returns new balance.
    """
    if amount <= 0:
        u = db.query(User).filter(User.id == user_id).first()
        if not u:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        return int(u.credit_balance or 0)

    user = _user_query_for_update(db, user_id).one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    bal = int(user.credit_balance or 0)
    if bal < amount:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "message": "Không đủ credit.",
                "balance": bal,
                "required": amount,
                "reason": reason,
            },
        )

    user.credit_balance = bal - amount
    db.add(
        CreditLedger(
            user_id=user_id,
            delta=-amount,
            balance_after=int(user.credit_balance),
            reason=reason[:64],
            note=(note or "")[:2000] or None,
        )
    )
    return int(user.credit_balance)


def grant_credits(
    db: Session,
    *,
    user_id: int,
    amount: int,
    reason: str,
    note: str | None = None,
) -> int:
    """Add credits (admin or signup). Caller must commit."""
    if amount <= 0:
        u = db.query(User).filter(User.id == user_id).first()
        if not u:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return int(u.credit_balance or 0)

    user = _user_query_for_update(db, user_id).one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    bal = int(user.credit_balance or 0)
    user.credit_balance = bal + amount
    db.add(
        CreditLedger(
            user_id=user_id,
            delta=amount,
            balance_after=int(user.credit_balance),
            reason=reason[:64],
            note=(note or "")[:2000] or None,
        )
    )
    return int(user.credit_balance)


def apply_signup_bonus_if_configured(db: Session, user: User) -> None:
    b = signup_bonus()
    if b <= 0:
        return
    grant_credits(db, user_id=user.id, amount=b, reason="signup_bonus", note=None)
