"""Cost-control SSOT: credit prices, cluster formula, image band."""

from __future__ import annotations

import unittest

from app.services.content_ai_openrouter_images import credit_cost_for_images, credits_per_image
from app.services.credit_cost_registry import (
    cluster_credit_cost,
    index_submit_credit_cost,
    resolve_credit_cost,
)


class CostControlSsotTests(unittest.TestCase):
    def test_ai_image_band_50_55(self) -> None:
        cost = resolve_credit_cost("content_ai", "ai_image")
        self.assertGreaterEqual(cost, 50)
        self.assertLessEqual(cost, 55)
        per = credits_per_image("google/gemini-2.5-flash-image")
        self.assertGreaterEqual(per, 50)
        self.assertLessEqual(per, 55)
        self.assertEqual(credit_cost_for_images(model="google/gemini-2.5-flash-image", count=2), per * 2)

    def test_lead_and_audit_and_research(self) -> None:
        scan = resolve_credit_cost("lead_scanner", "basic_scan")
        self.assertGreaterEqual(scan, 40)
        self.assertLessEqual(scan, 45)
        detail = resolve_credit_cost("lead_scanner", "place_detail")
        self.assertGreaterEqual(detail, 20)
        self.assertLessEqual(detail, 25)
        deep = resolve_credit_cost("content_ai", "addon_research")
        self.assertGreaterEqual(deep, 20)
        self.assertLessEqual(deep, 25)
        self.assertEqual(resolve_credit_cost("audit", "technical_deep"), 15)

    def test_keyword_research_kept(self) -> None:
        self.assertEqual(resolve_credit_cost("keyword", "research_run"), 30)
        self.assertEqual(resolve_credit_cost("keyword", "research_cache"), 5)

    def test_cluster_scales_with_keywords(self) -> None:
        small = cluster_credit_cost(40, async_job=True, fetch_serp=False)
        large = cluster_credit_cost(200, async_job=True, fetch_serp=False)
        serp = cluster_credit_cost(40, async_job=True, fetch_serp=True)
        self.assertGreaterEqual(small, 2)
        self.assertGreater(large, small)
        self.assertGreater(serp, small)
        self.assertGreaterEqual(resolve_credit_cost("keyword", "cluster_serp_block"), 9)

    def test_previously_unmetered_have_cost(self) -> None:
        self.assertGreaterEqual(resolve_credit_cost("wordpress", "publish"), 1)
        self.assertGreaterEqual(index_submit_credit_cost(1, provider="google"), 1)
        self.assertGreaterEqual(index_submit_credit_cost(25, provider="indexnow"), 1)
        self.assertGreaterEqual(resolve_credit_cost("embedding", "openai_batch"), 1)


if __name__ == "__main__":
    unittest.main()
