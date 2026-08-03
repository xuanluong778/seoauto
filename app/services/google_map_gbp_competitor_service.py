"""Google Map SEO — phân tích đối thủ Local Pack."""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from app.services.google_map_gbp_profile_service import _resolve_location

_LOG = logging.getLogger("google_map_gbp.competitors")

# Demo Local Pack — tách rõ khỏi API thật (Places / SERP chưa tích hợp)
_DEMO_PACKS: dict[str, dict[str, Any]] = {
    "dich-vu-seo|quan-1": {
        "radius_km": 3,
        "competitors": [
            {
                "rank": 1,
                "name": "Local Boost VN",
                "rating": 4.7,
                "reviews": 156,
                "category": "Dịch vụ SEO",
                "photo_count": 38,
                "posts_per_month": 3.5,
                "website": "https://localboost.vn",
                "estimated_score": 84,
                "distance": "0.9 km",
            },
            {
                "rank": 2,
                "name": "SEO Việt Pro",
                "rating": 4.6,
                "reviews": 198,
                "category": "Marketing Agency",
                "photo_count": 52,
                "posts_per_month": 2.0,
                "website": "https://seovietpro.vn",
                "estimated_score": 81,
                "distance": "1.2 km",
            },
            {
                "rank": 3,
                "name": "DigiSEO Agency",
                "rating": 4.8,
                "reviews": 127,
                "category": "Dịch vụ SEO",
                "photo_count": 22,
                "posts_per_month": 1.2,
                "website": "https://digiseo.vn",
                "estimated_score": 78,
                "distance": "—",
                "is_self": True,
            },
            {
                "rank": 4,
                "name": "TopRank Agency",
                "rating": 4.4,
                "reviews": 89,
                "category": "Marketing Agency",
                "photo_count": 15,
                "posts_per_month": 0.8,
                "website": "https://toprank.vn",
                "estimated_score": 68,
                "distance": "2.8 km",
            },
        ],
    },
    "marketing|thu-duc": {
        "radius_km": 5,
        "competitors": [
            {
                "rank": 1,
                "name": "Growth Map TP.HCM",
                "rating": 4.5,
                "reviews": 74,
                "category": "Marketing Agency",
                "photo_count": 28,
                "posts_per_month": 2.5,
                "website": "https://growthmap.vn",
                "estimated_score": 76,
                "distance": "1.5 km",
            },
            {
                "rank": 2,
                "name": "DigiSEO — Chi nhánh Thủ Đức",
                "rating": 4.5,
                "reviews": 43,
                "category": "Marketing Agency",
                "photo_count": 9,
                "posts_per_month": 0.5,
                "website": "https://digiseo.vn",
                "estimated_score": 62,
                "distance": "—",
                "is_self": True,
            },
            {
                "rank": 3,
                "name": "AdsLocal VN",
                "rating": 4.2,
                "reviews": 31,
                "category": "Quảng cáo",
                "photo_count": 12,
                "posts_per_month": 1.0,
                "website": "",
                "estimated_score": 58,
                "distance": "2.1 km",
            },
        ],
    },
}


def _norm_key(keywords: str, locality: str) -> str:
    def slug(s: str) -> str:
        s = str(s or "").lower().strip()
        s = re.sub(r"[^a-z0-9àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ\s-]+", " ", s)
        s = re.sub(r"\s+", "-", s).strip("-")
        return s[:48]

    return f"{slug(keywords)}|{slug(locality)}"


def _pick_demo_pack(keywords: str, locality: str) -> dict[str, Any] | None:
    key = _norm_key(keywords, locality)
    if key in _DEMO_PACKS:
        return _DEMO_PACKS[key]
    kw = str(keywords or "").lower()
    loc = str(locality or "").lower()
    if "seo" in kw or "marketing" in kw:
        if "quận 1" in loc or "quan 1" in loc or "q1" in loc:
            return _DEMO_PACKS["dich-vu-seo|quan-1"]
        if "thủ đức" in loc or "thu duc" in loc:
            return _DEMO_PACKS["marketing|thu-duc"]
        return _DEMO_PACKS["dich-vu-seo|quan-1"]
    return None


def _merge_self_from_gbp(
    competitors: list[dict[str, Any]],
    *,
    business_name: str,
    category: str,
    website: str,
    reviews: int | None,
    rating: float | None,
    photo_count: int | None,
    map_score: int | None,
) -> list[dict[str, Any]]:
    """Cập nhật hàng is_self bằng số liệu GBP thật nếu có — không bịa."""
    out: list[dict[str, Any]] = []
    for c in competitors:
        row = dict(c)
        if row.get("is_self"):
            if business_name:
                row["name"] = business_name
            if category:
                row["category"] = category
            if website:
                row["website"] = website
            if reviews is not None:
                row["reviews"] = reviews
            if rating is not None:
                row["rating"] = rating
            if photo_count is not None:
                row["photo_count"] = photo_count
            if map_score is not None:
                row["estimated_score"] = map_score
        out.append(row)
    return out


def _build_actions(
    self_row: dict[str, Any] | None,
    competitors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not self_row or not competitors:
        return []
    others = [c for c in competitors if not c.get("is_self")]
    if not others:
        return []

    leader = max(others, key=lambda x: int(x.get("reviews") or 0))
    actions: list[dict[str, Any]] = []

    def add(priority: str, metric: str, gap: str, action: str) -> None:
        actions.append({"priority": priority, "metric": metric, "gap": gap, "action": action})

    self_rev = int(self_row.get("reviews") or 0)
    lead_rev = int(leader.get("reviews") or 0)
    if lead_rev > self_rev:
        add(
            "high",
            "Review",
            f"Bạn {self_rev} · #{leader.get('rank')} có {lead_rev}",
            f"Thu thập thêm ~{lead_rev - self_rev} review chất lượng (ưu tiên sau dịch vụ).",
        )

    self_rating = float(self_row.get("rating") or 0)
    lead_rating = float(leader.get("rating") or 0)
    if lead_rating > self_rating + 0.05:
        add(
            "medium",
            "Điểm sao",
            f"{self_rating:.1f} vs {lead_rating:.1f}",
            "Cải thiện trải nghiệm khách và phản hồi review tiêu cực.",
        )

    self_photos = int(self_row.get("photo_count") or 0)
    avg_photos = sum(int(c.get("photo_count") or 0) for c in others) / len(others)
    if self_photos < avg_photos:
        add(
            "high",
            "Ảnh",
            f"{self_photos} ảnh · TB đối thủ {avg_photos:.0f}",
            "Bổ sung ảnh thật: mặt tiền, đội ngũ, sản phẩm/dịch vụ.",
        )

    self_posts = float(self_row.get("posts_per_month") or 0)
    lead_posts = max(float(c.get("posts_per_month") or 0) for c in others)
    if lead_posts > self_posts + 0.3:
        add(
            "medium",
            "Bài đăng",
            f"{self_posts:.1f}/tháng vs tối đa {lead_posts:.1f}",
            "Lên lịch 2–4 bài đăng Google Map/tháng (ưu đãi, case study).",
        )

    self_score = int(self_row.get("estimated_score") or 0)
    lead_score = max(int(c.get("estimated_score") or 0) for c in others)
    if lead_score > self_score:
        add(
            "high",
            "Điểm tối ưu",
            f"{self_score} vs {lead_score}",
            f"Chạy Check Map Score và xử lý lỗi Critical/Warning để tăng ~{lead_score - self_score} điểm.",
        )

    if not self_row.get("website"):
        add("medium", "Website", "Chưa có", "Thêm website và đồng bộ NAP với Google Map.")

    if not actions:
        add("low", "Tổng thể", "—", "Duy trì review mới và bài đăng định kỳ để giữ hạng.")

    return actions


def analyze_competitors(
    db: Session,
    user_id: int,
    *,
    location_key: str,
    keywords: str,
    locality: str,
) -> dict[str, Any]:
    kw = str(keywords or "").strip()
    loc = str(locality or "").strip()
    gbp_row, loc_ui = _resolve_location(db, user_id, location_key)

    # API Places / Local Pack chưa tích hợp — chỉ demo hoặc insufficient
    source = "demo"
    pack = _pick_demo_pack(kw, loc)
    if pack is None:
        return {
            "source": "insufficient",
            "source_label": "Chưa đủ dữ liệu",
            "message": (
                "Chưa có API Local Pack / Places để lấy đối thủ thật. "
                "Thử từ khóa «dịch vụ SEO» + «Quận 1» để xem dữ liệu mẫu minh họa."
            ),
            "keyword": kw,
            "locality": loc,
            "radius_km": None,
            "competitors": [],
            "self_entry": None,
            "actions": [],
            "summary": None,
        }

    competitors = [dict(c) for c in pack["competitors"]]

    # Nếu đã kết nối GBP — chỉ ghi đè số liệu THẬT của chính user, không bịa đối thủ
    gbp_enriched = False
    if gbp_row and loc_ui:
        reviews = None
        rating = None
        photo_count = None
        map_score = None
        audit = None
        if gbp_row.audit_snapshot_json:
            try:
                import json

                audit = json.loads(gbp_row.audit_snapshot_json)
            except Exception:
                audit = None
        if audit and isinstance(audit.get("reviews"), dict):
            reviews = audit["reviews"].get("count")
            rating = audit["reviews"].get("avgRating")
        if audit and isinstance(audit.get("media"), dict):
            photo_count = audit["media"].get("photoCount")
        competitors = _merge_self_from_gbp(
            competitors,
            business_name=str(loc_ui.get("name") or ""),
            category=str(loc_ui.get("category") or ""),
            website=str(loc_ui.get("website") or ""),
            reviews=int(reviews) if reviews is not None else None,
            rating=float(rating) if rating is not None else None,
            photo_count=int(photo_count) if photo_count is not None else None,
            map_score=map_score,
        )
        gbp_enriched = True

    self_entry = next((c for c in competitors if c.get("is_self")), None)
    others = [c for c in competitors if not c.get("is_self")]
    summary = None
    if self_entry and others:
        self_rank = int(self_entry.get("rank") or 0)
        leader = min(others, key=lambda x: int(x.get("rank") or 99))
        summary = {
            "your_rank": self_rank,
            "leader_name": leader.get("name"),
            "leader_reviews": leader.get("reviews"),
            "your_reviews": self_entry.get("reviews"),
            "review_gap": int(leader.get("reviews") or 0) - int(self_entry.get("reviews") or 0),
        }

    actions = _build_actions(self_entry, competitors)

    return {
        "source": source,
        "source_label": "Dữ liệu mẫu (demo)" + (" · đã gắn số liệu GBP của bạn" if gbp_enriched else ""),
        "message": None,
        "keyword": kw,
        "locality": loc,
        "radius_km": pack.get("radius_km"),
        "competitors": sorted(competitors, key=lambda x: int(x.get("rank") or 99)),
        "self_entry": self_entry,
        "actions": actions,
        "summary": summary,
        "disclaimer": "Số liệu đối thủ từ bộ demo — không phải kết quả Google thời gian thực cho đến khi tích hợp Places API.",
    }
