"""
SERP feature density from API extras or lightweight heuristics on organic rows.
"""

from __future__ import annotations

import re
from typing import Any


def detect_serp_features(serp_payload: dict[str, Any]) -> dict[str, Any]:
    """
    ``serp_payload``: output of ``fetch_serp`` (may include ``raw_api_extras`` from SerpAPI).

    Heuristic flags when API did not return structured features (e.g. mock mode).
    """
    extras = dict(serp_payload.get("raw_api_extras") or {})
    organic = list(serp_payload.get("serp_results") or [])

    has_fs = bool(extras.get("answer_box"))
    has_ads = bool(extras.get("ads"))
    has_video = bool(extras.get("inline_videos"))
    has_faq = bool(extras.get("related_questions"))
    has_sitelinks = bool(extras.get("sitelinks"))

    if not extras and organic:
        blob = " ".join(
            str(r.get("title", "")) + " " + str(r.get("snippet", "")) for r in organic[:10]
        ).lower()
        if re.search(r"\b(how to|what is|why |when |steps?|guide)\b", blob):
            has_faq = True
        if "youtube" in blob or "video" in blob:
            has_video = True
        if "wikipedia" in blob or "definition" in blob:
            has_fs = True

    count = sum([has_fs, has_ads, has_video, has_faq, has_sitelinks])
    feature_density_score = round(count / 5.0, 3)

    return {
        "has_featured_snippet": has_fs,
        "has_ads": has_ads,
        "has_video": has_video,
        "has_faq": has_faq,
        "has_sitelinks": has_sitelinks,
        "feature_density_score": feature_density_score,
    }
