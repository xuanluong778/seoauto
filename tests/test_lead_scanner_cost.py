"""Tests for Lead Map Scanner cost controls."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.services.credits import quote_lead_basic_scan, quote_lead_detail
from app.services.google_map_lead_scanner_service import build_cache_key, _dedupe_leads


class LeadScannerCostTests(unittest.TestCase):
    def test_basic_quote_excludes_details(self) -> None:
        q = quote_lead_basic_scan(mode="keyword", limit=50, from_cache=False)
        self.assertGreater(q["credit_required"], 0)
        self.assertEqual(q["detail_calls"], 0)
        self.assertEqual(q["detail_cost"], 0)

    def test_cache_quote_discounted(self) -> None:
        live = quote_lead_basic_scan(mode="keyword", limit=50, from_cache=False)
        q = quote_lead_basic_scan(mode="keyword", limit=50, from_cache=True)
        self.assertGreater(q["credit_required"], 0)
        self.assertLess(q["credit_required"], live["credit_required"])

    def test_detail_quote_scales(self) -> None:
        q = quote_lead_detail(3)
        self.assertEqual(q["detail_calls"], 3)
        self.assertGreater(q["credit_required"], 0)

    def test_cache_key_stable(self) -> None:
        params = {
            "mode": "keyword",
            "keyword": "spa quận 1",
            "province": "TP.HCM",
            "district": "Quận 1",
            "radius_km": 5,
            "limit": 20,
        }
        k1 = build_cache_key(1, params)
        k2 = build_cache_key(1, params)
        k3 = build_cache_key(2, params)
        self.assertEqual(k1, k2)
        self.assertNotEqual(k1, k3)

    def test_dedupe_by_place_phone_website(self) -> None:
        rows = [
            {"place_id": "a", "phone": "0901234567", "website": "https://a.com"},
            {"place_id": "b", "phone": "0901234567", "website": ""},
            {"place_id": "c", "phone": "", "website": "https://a.com"},
            {"place_id": "d", "phone": "", "website": ""},
        ]
        out = _dedupe_leads(rows)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["place_id"], "a")
        self.assertEqual(out[1]["place_id"], "d")

    @patch("app.services.cost_control.gate.ensure_sufficient_credits")
    @patch("app.services.cost_control.gate.credits_enforced", return_value=True)
    @patch("app.services.cost_control.gate.cost_control_enforced", return_value=True)
    def test_insufficient_credit_blocks_before_api(self, _cc, _enf, mock_balance) -> None:
        from fastapi import HTTPException

        from app.services.google_map_lead_scanner_service import run_scan

        mock_balance.return_value = (5, False)
        db = MagicMock()
        user = MagicMock()
        user.id = 99
        user.role = "user"
        with patch("app.services.cost_control.gate.is_admin", return_value=False), patch(
            "app.services.cost_control.gate.user_has_software_access", return_value=True
        ), patch(
            "app.services.cost_control.gate.resolve_cau_ai_plan_slug", return_value="pro"
        ), patch(
            "app.services.saas_economics_guard.assert_expensive_api_allowed"
        ), patch(
            "app.services.cost_control.caps.assert_user_credit_caps"
        ), patch(
            "app.services.cost_control.caps.assert_provider_daily_caps"
        ), patch(
            "app.services.cost_control.gate.check_user_rate_limit"
        ), patch(
            "app.services.cost_control.gate.check_user_concurrency"
        ), patch(
            "app.services.cost_control.gate.release_user_concurrency"
        ), patch(
            "app.services.google_map_lead_scanner_service._find_cached_scan",
            return_value=None,
        ), patch(
            "app.services.google_map_lead_scanner_service._check_plan_limits",
            return_value={},
        ), patch(
            "app.services.google_map_lead_scanner_service.resolve_cau_ai_plan_slug",
            return_value="pro",
        ), patch(
            "app.services.google_map_lead_scanner_service.lead_scanner_enabled",
            return_value=True,
        ), patch(
            "app.services.google_map_lead_scanner_service.places_api_configured",
            return_value=True,
        ), patch(
            "app.services.cost_control.executor.guarded_requests_post"
        ) as mock_post, patch(
            "app.services.cost_control.executor.guarded_requests_get"
        ) as mock_get:
            with self.assertRaises(HTTPException) as ctx:
                run_scan(
                    db,
                    user,
                    {
                        "mode": "keyword",
                        "keyword": "spa",
                        "limit": 20,
                        "radius_km": 5,
                    },
                )
        self.assertEqual(ctx.exception.status_code, 402)
        mock_post.assert_not_called()
        mock_get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
