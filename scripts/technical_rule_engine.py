"""Rule engine ngữ cảnh: severity + confidence + explanation (giảm false positive)."""

from __future__ import annotations

from typing import Any, Literal

from app.services.page_type_detect import PageType

Severity = Literal["high", "medium", "low"]


def _issue(
    type_: str,
    severity: Severity,
    message: str,
    *,
    confidence: float,
    explanation: str,
    checklist_group: str = "Onpage",
) -> dict[str, Any]:
    return {
        "type": type_,
        "severity": severity,
        "message": message,
        "checklist_group": checklist_group,
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "explanation": explanation,
    }


def build_contextual_onpage_issues(
    parsed: dict[str, Any],
    page_type: PageType,
    page_url: str,
) -> list[dict[str, Any]]:
    """Từ structured parse + page type → danh sách issue dict (chưa gán url trang)."""
    issues: list[dict[str, Any]] = []
    status = int(parsed.get("status") or 0)
    if status != 200:
        issues.append(
            _issue(
                "http_status_error",
                "high",
                f"Trang trả HTTP {status}.",
                confidence=0.99,
                explanation="Status lấy từ tài liệu đã render; không phải suy đoán từ HTML.",
                checklist_group="Onpage",
            )
        )
        return issues

    title = (parsed.get("title") or "").strip()
    meta = (parsed.get("meta_description") or "").strip()
    canonical = (parsed.get("canonical") or "").strip()
    h1_count = int(parsed.get("h1_count") or 0)
    word_count = int(parsed.get("word_count") or 0)
    img_miss = int(parsed.get("images_missing_alt") or 0)
    robots = (parsed.get("robots_meta") or "").lower()

    if "noindex" in robots:
        issues.append(
            _issue(
                "robots_noindex",
                "medium",
                "Meta robots chứa noindex — trang có thể không được index.",
                confidence=0.95,
                explanation=f"Giá trị robots: «{parsed.get('robots_meta') or ''}».",
                checklist_group="GSC",
            )
        )

    if not title:
        issues.append(
            _issue(
                "missing_title",
                "high",
                "Thiếu thẻ <title>.",
                confidence=0.98,
                explanation="Đã parse DOM sau render; title rỗng.",
            )
        )
    elif len(title) > 60:
        issues.append(
            _issue(
                "title_too_long",
                "medium",
                f"Title dài {len(title)} ký tự (thường khuyến nghị ~≤60 ký tự hiển thị SERP).",
                confidence=0.55,
                explanation="Ngưỡng mang tính hướng dẫn; SERP có thể cắt khác nhau.",
            )
        )

    if not meta:
        sev: Severity = "high" if page_type in ("article", "homepage", "landing") else "medium"
        conf = 0.85 if page_type in ("article", "homepage", "landing") else 0.5
        issues.append(
            _issue(
                "missing_meta_description",
                sev,
                "Thiếu meta description.",
                confidence=conf,
                explanation=f"Loại trang ước lượng: {page_type}. Category/listing thường ít ưu tiên meta độc lập.",
            )
        )

    if not canonical:
        sev2: Severity = "medium" if page_type in ("article", "homepage") else "low"
        conf2 = 0.75 if page_type in ("article", "homepage") else 0.45
        issues.append(
            _issue(
                "missing_canonical",
                sev2,
                "Không có link rel=canonical.",
                confidence=conf2,
                explanation="Nhiều site dùng mặc định URL; canonical vẫn nên có cho trang quan trọng.",
            )
        )

    if h1_count == 0:
        if page_type in ("article", "landing"):
            issues.append(
                _issue(
                    "missing_h1",
                    "high",
                    "Không có H1.",
                    confidence=0.9,
                    explanation=f"Với {page_type}, H1 thường bắt buộc cho cấu trúc heading.",
                )
            )
        elif page_type == "homepage":
            issues.append(
                _issue(
                    "missing_h1",
                    "medium",
                    "Không có H1.",
                    confidence=0.55,
                    explanation="Homepage đôi khi dùng hero/logo thay H1 — kiểm tra thủ công.",
                )
            )
        else:
            issues.append(
                _issue(
                    "missing_h1",
                    "low",
                    "Không có H1.",
                    confidence=0.4,
                    explanation=f"Loại {page_type}: ít nghiêm hơn article/landing.",
                )
            )
    elif h1_count > 1:
        issues.append(
            _issue(
                "multiple_h1",
                "medium",
                f"Có {h1_count} thẻ H1.",
                confidence=0.8,
                explanation="Nhiều H1 có thể gây nhiễu tín hiệu heading; không luôn là lỗi nếu layout đặc thù.",
            )
        )

    if word_count < 300:
        if page_type in ("article", "landing"):
            issues.append(
                _issue(
                    "thin_content",
                    "medium",
                    f"Nội dung ~{word_count} từ (dưới 300).",
                    confidence=0.65,
                    explanation="Đếm từ sau loại script/style — có thể khác công cụ khác vài phần trăm.",
                )
            )
        elif page_type == "category":
            issues.append(
                _issue(
                    "thin_content",
                    "low",
                    f"Nội dung ~{word_count} từ.",
                    confidence=0.35,
                    explanation="Trang category thường ít text — không tương đương bài viết.",
                )
            )

    if img_miss > 0:
        issues.append(
            _issue(
                "images_missing_alt",
                "low",
                f"{img_miss} ảnh thiếu alt.",
                confidence=0.85,
                explanation="Ảnh trang trí/decorative vẫn có thể cần alt rỗng có chủ đích — rà soát tay.",
                checklist_group="Images",
            )
        )

    return issues
