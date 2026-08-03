"""Tests for credit cost registry."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.services.credit_cost_registry import (
    apply_cache_discount,
    content_ai_action_for_word_count,
    resolve_credit_cost,
    volume_batch_charge_from_registry,
)


class CreditCostRegistryTests(unittest.TestCase):
    def test_content_ai_word_tiers(self) -> None:
        self.assertEqual(content_ai_action_for_word_count(900), "article_short")
        self.assertEqual(content_ai_action_for_word_count(1500), "article_medium")
        self.assertEqual(content_ai_action_for_word_count(2500), "article_long")

    def test_article_short_cost_not_flat_five(self) -> None:
        cost = resolve_credit_cost("content_ai", "article_short")
        self.assertGreaterEqual(cost, 10)
        self.assertLessEqual(cost, 15)

    def test_cache_zero_cost(self) -> None:
        self.assertEqual(
            apply_cache_discount(12, from_cache=True, cache_zero_cost=True, cache_discount_percent=80),
            0,
        )

    def test_cache_discount_80_percent(self) -> None:
        self.assertEqual(
            apply_cache_discount(10, from_cache=True, cache_discount_percent=80, cache_zero_cost=False),
            2,
        )

    def test_cau_fix_cache_zero_from_registry(self) -> None:
        cost = resolve_credit_cost("cau", "seo_ai_fix", from_cache=True)
        self.assertEqual(cost, 0)

    def test_volume_batch_100_blocks(self) -> None:
        c100 = volume_batch_charge_from_registry(100)
        c50 = volume_batch_charge_from_registry(50)
        self.assertEqual(c100, c50)
        self.assertGreaterEqual(c100, 20)

    def test_admin_db_override(self) -> None:
        db = MagicMock()
        row = MagicMock()
        row.module = "content_ai"
        row.action = "article_short"
        row.credit_cost = 99
        row.cache_discount_percent = 50
        row.cache_zero_cost = False
        row.label = "Test"
        row.description = None
        db.query.return_value.filter.return_value.all.return_value = [row]
        with patch("app.services.credit_cost_registry.CreditCostConfig", create=True):
            cost = resolve_credit_cost("content_ai", "article_short", db=db)
        self.assertEqual(cost, 99)


if __name__ == "__main__":
    unittest.main()
