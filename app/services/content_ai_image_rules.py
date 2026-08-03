"""Quy tắc chèn ảnh Content AI — số lượng theo số từ, hướng ảnh theo loại dịch vụ."""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

Orientation = Literal["landscape", "portrait", "any"]
ImageSource = Literal["none", "google", "ai"]

LANDSCAPE_SIZE = (800, 500)
PORTRAIT_SIZE = (500, 800)

_PORTRAIT_KEYWORDS = (
    "ao cuoi",
    "áo cưới",
    "wedding",
    "cuoi",
    "cưới",
    "spa",
    "massage",
    "thoi trang",
    "thời trang",
    "fashion",
    "beauty",
    "lam dep",
    "làm đẹp",
    "makeup",
    "trang diem",
    "trang điểm",
    "nail",
    "salon",
    "toc",
    "tóc",
    "hair",
    "studio anh",
    "studio ảnh",
    "chan dung",
    "chân dung",
    "portrait",
    "vay",
    "váy",
    "dress",
    "cosmetic",
    "my pham",
    "mỹ phẩm",
    "skincare",
    "yoga",
    "pilates",
    "gym nu",
    "gym nữ",
)

_LANDSCAPE_KEYWORDS = (
    "sua may tinh",
    "sửa máy tính",
    "sua dien",
    "sửa điện",
    "dien lanh",
    "điện lạnh",
    "noi that",
    "nội thất",
    "interior",
    "may moc",
    "máy móc",
    "machinery",
    "repair",
    "computer",
    "laptop",
    "electrical",
    "plumbing",
    "ong nuoc",
    "ống nước",
    "xay dung",
    "xây dựng",
    "construction",
    "kien truc",
    "kiến trúc",
    "factory",
    "nha xuong",
    "nhà xưởng",
    "warehouse",
    "logistics",
    "van tai",
    "vận tải",
    "oto",
    "ô tô",
    "automotive",
    "industrial",
    "cong nghiep",
    "công nghiệp",
)


def _fold(text: str) -> str:
    raw = unicodedata.normalize("NFC", str(text or "").strip().lower())
    raw = raw.replace("đ", "d")
    return unicodedata.normalize("NFC", raw)


def inline_image_count_for_word_count(word_count: int | None) -> int:
    """Số ảnh inline chèn sau H2 theo độ dài bài."""
    wc = max(0, int(word_count or 0))
    if wc >= 2000:
        return 4
    if wc >= 1500:
        return 3
    if wc >= 1000:
        return 2
    if wc >= 500:
        return 1
    return 0


def image_credit_slots(word_count: int | None, *, include_featured: bool = True) -> int:
    """Số slot ảnh tính credit (inline + ảnh đại diện nếu bật)."""
    inline = inline_image_count_for_word_count(word_count)
    if inline <= 0:
        return 0
    return inline + (1 if include_featured else 0)


def resolve_image_orientation(
    *,
    industry: str = "",
    keyword: str = "",
    brand_name: str = "",
    section_heading: str = "",
) -> Orientation:
    """Ưu tiên dọc (spa, thời trang…) hoặc ngang (sửa chữa, nội thất…)."""
    blob = _fold(" ".join((industry, keyword, brand_name, section_heading)))
    if not blob.strip():
        return "any"
    portrait_hits = sum(1 for k in _PORTRAIT_KEYWORDS if k in blob)
    landscape_hits = sum(1 for k in _LANDSCAPE_KEYWORDS if k in blob)
    if portrait_hits > landscape_hits and portrait_hits > 0:
        return "portrait"
    if landscape_hits > portrait_hits and landscape_hits > 0:
        return "landscape"
    return "any"


def strategy_from_image_source(source: str | None) -> str | None:
    """Map nguồn UI → CONTENT_AI strategy: web | ai."""
    raw = str(source or "").strip().lower()
    if raw in ("google", "web"):
        return "web"
    if raw == "ai":
        return "ai"
    return None


def normalize_image_source(source: str | None, *, include_images: bool = False) -> ImageSource:
    raw = str(source or "").strip().lower()
    if raw in ("google", "web"):
        return "google"
    if raw == "ai":
        return "ai"
    if include_images:
        return "google"
    return "none"


def parse_image_source_choice(text: str) -> ImageSource | None:
    """Nhận lựa chọn nguồn ảnh từ chatbot."""
    folded = _fold(text)
    if not folded:
        return None
    if re.search(
        r"^(?:khong|không|bo|bỏ|none|0|skip|khong chen|không chèn|khong anh|không ảnh)",
        folded,
    ):
        return "none"
    if re.search(
        r"(?:google|tu google|từ google|lay anh|lấy ảnh|anh google|ảnh google|web|tim anh|tìm ảnh)",
        folded,
    ):
        return "google"
    if re.search(
        r"(?:\bai\b|tao anh|tạo ảnh|anh ai|ảnh ai|dung ai|dùng ai|generate)",
        folded,
    ):
        return "ai"
    return None


def image_source_label(source: str | None) -> str:
    raw = normalize_image_source(source)
    if raw == "google":
        return "Lấy ảnh từ Google"
    if raw == "ai":
        return "Tạo ảnh bằng AI"
    return "Không chèn ảnh"
