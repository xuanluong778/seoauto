"""Google Sites — manual copy workflow (no auto publish)."""

from __future__ import annotations

import html
import re
from typing import Any


def _strip_scripts(raw: str) -> str:
    return re.sub(r"<script\b[^>]*>.*?</script>", "", raw or "", flags=re.I | re.S)


def build_manual_package(post: dict[str, Any], main_site_url: str = "") -> dict[str, Any]:
    title = str(post.get("title") or "Bài viết Web 2.0").strip()
    slug = str(post.get("slug") or "").strip()
    if not slug:
        slug = re.sub(r"[^\w\s-]", "", title.lower(), flags=re.UNICODE)
        slug = re.sub(r"[\s_-]+", "-", slug).strip("-") or "bai-viet"
    excerpt = str(post.get("excerpt") or "").strip()
    body = _strip_scripts(str(post.get("html_content") or post.get("content") or ""))
    tags = post.get("tags") or []
    tag_line = ", ".join(str(t).strip() for t in tags if str(t).strip())
    cta = str(post.get("cta") or "").strip()
    if not cta and main_site_url:
        cta = f"Xem thêm tại {main_site_url}"
    elif not cta:
        cta = "Liên hệ hoặc truy cập website chính để biết thêm chi tiết."

    image_prompt = (
        f"Ảnh minh họa chuyên nghiệp cho bài «{title}». "
        "Phong cách hiện đại, sáng, phù hợp Google Sites, không chữ watermark."
    )

    clean_html = f"""<article>
<h1>{html.escape(title)}</h1>
{f'<p><em>{html.escape(excerpt)}</em></p>' if excerpt else ''}
{body}
{f'<p><strong>{html.escape(cta)}</strong></p>' if cta else ''}
</article>"""

    checklist = [
        "Mở Google Sites → trang cần đăng → Chèn → Embed → Embed code.",
        "Dán HTML sạch bên dưới (hoặc copy từng khối nếu Sites không nhận full HTML).",
        "Tạo ảnh minh họa theo Image prompt, upload thủ công lên Google Sites.",
        "Kiểm tra tiêu đề, slug URL, excerpt và link về site chính (tối đa 2–3 link).",
        "Xem bản xem trước trên Google Sites trước khi Publish.",
        "Không dùng cookie / automation — thao tác thủ công trên sites.google.com.",
    ]
    if main_site_url:
        checklist.insert(3, f"Link site chính gợi ý: {main_site_url}")

    plain = re.sub(r"<[^>]+>", "\n", clean_html)
    plain = re.sub(r"\n{3,}", "\n\n", plain).strip()

    copy_bundle = "\n\n".join(
        x
        for x in [
            f"TITLE\n{title}",
            f"SLUG\n{slug}",
            f"EXCERPT\n{excerpt}" if excerpt else "",
            f"IMAGE PROMPT\n{image_prompt}",
            f"CTA\n{cta}",
            f"TAGS\n{tag_line}" if tag_line else "",
            f"HTML\n{clean_html}",
        ]
        if x
    )

    return {
        "title": title,
        "slug": slug,
        "excerpt": excerpt,
        "image_prompt": image_prompt,
        "cta": cta,
        "html": clean_html,
        "plain_text": plain,
        "copy_bundle": copy_bundle,
        "checklist": checklist,
        "tags": tag_line,
        "mode": "manual",
    }


class GoogleSitesManualProvider:
    platform = "google_sites_manual"

    def test_connection(self, account: dict[str, Any], secrets: dict[str, Any]) -> dict[str, Any]:
        label = str(account.get("label") or "Google Sites Manual")
        return {"ok": True, "message": f"{label} — không cần OAuth, copy thủ công."}

    def list_destinations(self, account: dict[str, Any], secrets: dict[str, Any]) -> list[dict[str, Any]]:
        label = str(account.get("label") or "Google Sites Manual")
        return [{"id": account.get("id"), "name": label, "url": str(account.get("site_url") or "")}]

    def publish_post(self, account: dict[str, Any], secrets: dict[str, Any], post: dict[str, Any]) -> dict[str, Any]:
        main_url = str(account.get("main_site_url") or post.get("main_site_url") or "")
        package = build_manual_package(post, main_site_url=main_url)
        return {
            "external_id": None,
            "published_url": "",
            "status": "manual",
            "mode": "manual",
            "manual_package": package,
        }
