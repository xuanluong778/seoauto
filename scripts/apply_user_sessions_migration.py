"""Apply user_sessions migration at deploy time (WAVE 8)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.migrations.ensure_user_sessions import apply_user_sessions_migration  # noqa: E402


def main() -> int:
    result = apply_user_sessions_migration()
    ok = bool(result.get("status", {}).get("ok"))
    print(result)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
