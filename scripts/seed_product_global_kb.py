#!/usr/bin/env python3
"""Import giá Seoauto vào KB global (sơ đồ tri thức sản phẩm)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.services.ai_knowledge_docs import _write_store, get_kb_stats, import_text
from app.services.product_knowledge import GLOBAL_PRODUCT_KB_ID

CHECKLIST = Path("data/digiseo-pricing-knowledge.txt")
HEADER = (
    "# SƠ ĐỒ TRI THỨC — GIÁ PHẦN MỀM Seoauto (GLOBAL)\n\n"
    "Dùng chung cho chatbot và AI — chỉ nêu giá theo tài liệu này.\n\n"
)


def main() -> None:
    if not CHECKLIST.is_file():
        raise SystemExit(f"Thiếu file: {CHECKLIST}")
    text = CHECKLIST.read_text(encoding="utf-8")
    _write_store(GLOBAL_PRODUCT_KB_ID, {"documents": []})
    import_text(
        GLOBAL_PRODUCT_KB_ID,
        "Sơ đồ tri thức — Giá phần mềm Seoauto",
        HEADER + text,
        embed=False,
    )
    print(f"OK — KB {GLOBAL_PRODUCT_KB_ID}", get_kb_stats(GLOBAL_PRODUCT_KB_ID))


if __name__ == "__main__":
    main()
