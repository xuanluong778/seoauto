#!/usr/bin/env python3
"""Import checklist Technical SEO vào KB global (chạy từ thư mục gốc dự án)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.services.ai_knowledge_docs import _write_store, get_kb_stats, import_text
from app.services.technical_knowledge import GLOBAL_TECHNICAL_KB_ID

KB_ID = GLOBAL_TECHNICAL_KB_ID
CHECKLIST = Path("data/checklist-technical-seo-so-do-tri-thuc.txt")
HEADER = (
    "# SƠ ĐỒ TRI THỨC — Seoauto (GLOBAL)\n\n"
    "Knowledge graph dùng chung cho mọi website Seoauto.\n\n"
)


def main() -> None:
    if not CHECKLIST.is_file():
        raise SystemExit(f"Thiếu file: {CHECKLIST}")
    text = CHECKLIST.read_text(encoding="utf-8")
    # Chỉ thêm/cập nhật checklist — không xóa tài liệu global khác trong KB.
    import_text(
        KB_ID,
        "Sơ đồ tri thức — Seoauto (Global)",
        HEADER + text,
        embed=False,
    )
    print(f"OK — KB {KB_ID}", get_kb_stats(KB_ID))


if __name__ == "__main__":
    main()
