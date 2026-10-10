"""Plan margin hard caps + infra cost usage metering."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.services.cost_control.plan_margin import (
    evaluate_all_plan_margins,
    resolve_expensive_category,
    worst_case_plan_margin,
)
from app.services.cost_usage_logger import estimate_cost_vnd
from app.services.credit_cost_registry import resolve_credit_cost


class PlanMarginSafeTests(unittest.TestCase):
    def test_all_paid_plans_pass_70gm_with_hard_caps(self) -> None:
        report = evaluate_all_plan_margins()
        self.assertTrue(report["all_pass"], report)
        for row in report["plans"]:
            self.assertGreaterEqual(row["gross_margin"], 0.70, row)
            self.assertTrue(row["pass_70gm"], row)
            self.assertLessEqual(row["worst_case_cost_vnd"], row["max_cost_for_70gm"], row)

    def test_agency_business_caps_below_full_pool(self) -> None:
        for slug in ("agency", "business", "pro"):
            row = worst_case_plan_margin(slug)
            self.assertLess(row["expensive_credit_cap_total"], row["included_credits"])

    def test_resolve_categories(self) -> None:
        self.assertEqual(resolve_expensive_category(action="ai_image"), "ai_image")
        self.assertEqual(resolve_expensive_category(provider="google_places"), "places_lead")
        self.assertEqual(resolve_expensive_category(provider="dataforseo"), "dataforseo_live")
        self.assertEqual(resolve_expensive_category(action="article_long"), "premium_llm")

    def test_premium_llm_cap_no_longer_product_blocks(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        from app.services.cost_control.plan_margin import assert_expensive_feature_monthly_cap

        db = MagicMock()
        user = SimpleNamespace(id=1, role="user")
        with patch(
            "app.services.cost_control.plan_margin.monthly_expensive_credits_used",
            return_value=9999,
        ):
            # Must not raise — wallet/entitlement are SSOT, not category hard caps.
            assert_expensive_feature_monthly_cap(
                db, user, category="premium_llm", extra_credits=45, plan_slug="pro"
            )


class InfraMeterRegistryTests(unittest.TestCase):
    def test_storage_and_crawl_email_registered(self) -> None:
        self.assertEqual(resolve_credit_cost("crawl", "job"), 2)
        self.assertEqual(resolve_credit_cost("email", "user_notify"), 1)
        self.assertEqual(resolve_credit_cost("storage", "put"), 0)
        self.assertEqual(resolve_credit_cost("storage", "r2_put"), 0)
        self.assertGreater(estimate_cost_vnd("crawl_job"), 0)
        self.assertGreater(estimate_cost_vnd("email_user_notify"), 0)
        self.assertGreater(estimate_cost_vnd("storage_put", bytes_len=4096), 0)

    def test_record_infra_cost_usage_metadata(self) -> None:
        from app.services.cost_usage_logger import record_infra_cost_usage

        db = MagicMock()
        with patch(
            "app.services.usage_tracking_service.record_successful_usage",
            return_value=MagicMock(),
        ) as mock_rec:
            record_infra_cost_usage(
                db,
                user_id=9,
                organization_id=9,
                feature_key="crawl_job",
                quantity=2,
                estimated_cost=160,
                provider="crawl",
                request_id="crawl:1:0",
                credits_used=0,
            )
            kwargs = mock_rec.call_args.kwargs
            self.assertEqual(kwargs["credits_used"], 0)
            self.assertEqual(kwargs["metadata"]["organization_id"], 9)
            self.assertEqual(kwargs["metadata"]["feature_key"], "crawl_job")
            self.assertEqual(kwargs["metadata"]["quantity"], 2)
            self.assertEqual(kwargs["metadata"]["estimated_cost"], 160)
            self.assertEqual(kwargs["metadata"]["provider"], "crawl")
            self.assertEqual(kwargs["metadata"]["request_id"], "crawl:1:0")


if __name__ == "__main__":
    unittest.main()
