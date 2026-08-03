"""
Tri thức sản phẩm Seoauto — giá gói, trial, thanh toán (global KB).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.ai_knowledge_docs import search_kb

GLOBAL_PRODUCT_KB_ID = (os.getenv("PRODUCT_GLOBAL_KB_ID") or "digiseo-product-global-001").strip()

_PRICING_PATH = Path(os.getenv("PRODUCT_PRICING_KNOWLEDGE_PATH") or "data/digiseo-pricing-knowledge.txt")

# Đồng bộ với static/js/digiseo_pricing.js
_BASE_VND_6M: dict[str, int] = {
    "basic": 1_500_000,
    "pro": 2_490_000,
    "agency": 4_490_000,
    "unlimited": 6_990_000,
}
_LIFETIME_VND: dict[str, int] = {
    "basic": 12_500_000,
    "pro": 20_500_000,
    "agency": 37_000_000,
    "unlimited": 58_000_000,
}
_DURATION_FACTORS: dict[str, tuple[str, float | None]] = {
    "m6": ("6 tháng", 1.0),
    "y1": ("1 năm", 1.85),
    "y2": ("2 năm", 3.35),
    "life": ("Vĩnh viễn", None),
}

_PRICING_QUERY_TOKENS = (
    "giá",
    "gia",
    "gói",
    "goi",
    "pricing",
    "price",
    "bao nhiêu",
    "mua",
    "nâng cấp",
    "nang cap",
    "upgrade",
    "plan",
    "basic",
    "pro",
    "agency",
    "unlimited",
    "payos",
    "paypal",
    "vĩnh viễn",
    "vinh vien",
    "lifetime",
    "thanh toán",
    "thanh toan",
    "coupon",
    "affiliate",
    "hoa hồng",
    "trial",
    "dùng thử",
    "credit",
    "subscription",
    "đăng ký",
    "phần mềm",
    "phan mem",
    "Seoauto",
    "nâng cấp gói",
)


def get_global_product_kb_id() -> str:
    return GLOBAL_PRODUCT_KB_ID


def is_pricing_query(text: str) -> bool:
    t = str(text or "").lower()
    if not t:
        return False
    return any(tok in t for tok in _PRICING_QUERY_TOKENS)


def _fmt_vnd(n: int) -> str:
    return f"{int(n):,}".replace(",", ".") + "đ"


def pricing_summary_compact() -> str:
    """Tóm tắt giá 6 tháng + lifetime — luôn inject khi hỏi giá (chatbot)."""
    lines = [
        "Seoauto — Bảng giá tham chiếu (VND, PayOS):",
        "Mở modal: Upgrade plan / View pricing.",
    ]
    for pid, label in (
        ("basic", "Basic"),
        ("pro", "Pro ★"),
        ("agency", "Agency"),
        ("unlimited", "Unlimited"),
    ):
        b6 = _BASE_VND_6M[pid]
        life = _LIFETIME_VND[pid]
        y1 = int(round(b6 * 1.85))
        lines.append(f"- {label}: 6 tháng {_fmt_vnd(b6)} | 1 năm {_fmt_vnd(y1)} | Vĩnh viễn {_fmt_vnd(life)}")
    lines.append("Trial 7 ngày: thêm API key hợp lệ (Cài đặt → Khóa API). GSC: Pro+.")
    lines.append("Thanh toán online PayOS/PayPal: đang tích hợp — liên hệ admin nếu cần kích hoạt thủ công.")
    return "\n".join(lines)


@lru_cache(maxsize=2)
def _pricing_file_mtime() -> float:
    p = _PRICING_PATH
    if not p.is_file():
        return 0.0
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def search_product_knowledge(query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    kid = GLOBAL_PRODUCT_KB_ID
    if not kid:
        return []
    return search_kb(kid, query, limit=limit)


def build_product_kb_context(query: str, *, limit: int = 6, force_summary: bool = False) -> str:
    parts: list[str] = []
    if force_summary or is_pricing_query(query):
        parts.append(pricing_summary_compact())
    hits = search_product_knowledge(query, limit=limit)
    if hits:
        lines = ["Chi tiết Knowledge Base — Giá & Gói Seoauto:"]
        for h in hits:
            title = h.get("document_title") or "doc"
            snip = str(h.get("snippet") or "")[:520]
            lines.append(f"- [{title}] {snip}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def match_pricing_faq(message: str) -> str | None:
    """Trả lời nhanh FAQ giá phổ biến (không cần LLM)."""
    q = message.strip().lower()
    if not is_pricing_query(q):
        return None
    if any(x in q for x in ("pro", "gói pro", "goi pro")) and any(
        x in q for x in ("giá", "gia", "bao nhiêu", "price")
    ):
        return (
            "Gói **Pro** (phổ biến): 6 tháng **2.490.000đ** | 1 năm **4.606.500đ** | "
            "Vĩnh viễn **20.500.000đ**. Gồm GSC, 100 bài AI/tháng, 10 project, 3 thiết bị.\n"
            "Xem đầy đủ: **Upgrade plan** hoặc Cài đặt → Account → **View pricing**."
        )
    if any(x in q for x in ("basic", "gói basic")):
        return (
            "Gói **Basic**: 6 tháng **1.500.000đ** | 1 năm **2.775.000đ** | "
            "Vĩnh viễn **12.500.000đ**. 50 bài/tháng, 3 project — không có GSC."
        )
    if any(x in q for x in ("bảng giá", "bang gia", "các gói", "cac goi", "những gói")):
        return pricing_summary_compact() + "\n\nMở **Seoauto Pricing** trên app để chọn thời hạn PayOS/PayPal."
    if any(x in q for x in ("trial", "dùng thử", "dung thu", "miễn phí")):
        return (
            "**Dùng thử 7 ngày**: thêm API key hợp lệ tại **Cài đặt → Khóa API** (một lần/user). "
            "Hết hạn trial: chỉ xem dữ liệu cũ, không tạo mới."
        )
    if any(x in q for x in ("thanh toán", "mua", "payos", "paypal")):
        return (
            "Chọn gói trên modal **Seoauto Pricing** (PayOS VND / PayPal USD). "
            "Cổng thanh toán tự động đang tích hợp; nếu chưa thanh toán được, liên hệ **admin** kích hoạt gói thủ công."
        )
    return None


def resolve_pricing_reply(message: str) -> str | None:
    """Trả lời giá Seoauto — ưu tiên FAQ cụ thể, sau đó bảng tóm tắt chính thức."""
    if not is_pricing_query(message):
        return None
    specific = match_pricing_faq(message)
    if specific:
        return specific
    return (
        pricing_summary_compact()
        + "\n\nMở **Upgrade plan** (góc màn hình) hoặc **Cài đặt → Account → View pricing** "
        "để chọn 6 tháng / 1 năm / 2 năm / Vĩnh viễn và PayOS hoặc PayPal."
    )
