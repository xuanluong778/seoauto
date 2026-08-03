"""Google Sites — manual copy workflow (no auto publish)."""

from __future__ import annotations

import html
import re
from typing import Any


def _strip_scripts(raw: str) -> str:
    return re.sub(r"<script\b[^>]*>.*?</script>", "", raw or "", flags=re.I | re.S)


def build_manual_package(post: dict[str, Any], main_site_url: str = "") -> dict[str, Any]:
    title = str(post.get("title") or "Bài viết Web 2.0").strip()
    excerpt = str(post.get("excerpt") or "").strip()
    body = _strip_scripts(str(post.get("html_content") or post.get("content") or ""))
    tags = post.get("tags") or []
    tag_line = ", ".join(str(t).strip() for t in tags if str(t).strip())

    clean_html = f"""<article>
<h1>{html.escape(title)}</h1>
{f'<p><em>{html.escape(excerpt)}</em></p>' if excerpt else ''}
{body}
</article>"""

    checklist = [
        "Mở Google Sites → trang cần đăng → Chèn → Embed → Embed code.",
        "Dán HTML sạch bên dưới (hoặc copy từng khối nếu Sites không nhận full HTML).",
        "Kiểm tra tiêu đề, ảnh và link về site chính (tối đa 2–3 link).",
        "Xem bản xem trước trên Google Sites trước khi Publish.",
        "Không dùng cookie / automation — thao tác thủ công trên sites.google.com.",
    ]
    if main_site_url:
        checklist.insert(2, f"Link site chính gợi ý: {main_site_url}")

    plain = re.sub(r"<[^>]+>", "\n", clean_html)
    plain = re.sub(r"\n{3,}", "\n\n", plain).strip()

    return {
        "title": title,
        "html": clean_html,
        "plain_text": plain,
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
