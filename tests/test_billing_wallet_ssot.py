"""Billing SSOT: wallet + entitlement; no hidden premium_llm product hard cap."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.services.content_ai_credit_service import quote_content_ai_write, reserve_content_ai_write
from app.services.cost_control.gate import CostGateRequest, cost_gate_session
from app.services.cost_control.plan_margin import assert_expensive_feature_monthly_cap
from app.services.cost_control.types import ExternalApiProvider
from app.services.plan_quota_registry import plan_feature


_GATE_SAFE = (
    ("app.services.cost_control.gate.user_has_software_access", {"return_value": True}),
    ("app.services.saas_gate.user_has_software_access", {"return_value": True}),
    ("app.services.saas_gate.enforce_saas_access", {"return_value": "pro"}),
    ("app.services.cost_control.gate.resolve_cau_ai_plan_slug", {"return_value": "pro"}),
    ("app.services.saas_economics_guard.assert_expensive_api_allowed", {}),
    ("app.services.cost_control.caps.assert_user_credit_caps", {}),
    ("app.services.cost_control.caps.assert_provider_daily_caps", {}),
    ("app.services.cost_control.gate.check_user_rate_limit", {}),
    ("app.services.cost_control.gate.check_user_concurrency", {}),
    ("app.services.cost_control.gate.release_user_concurrency", {}),
)


class PremiumHiddenCapRemovedTests(unittest.TestCase):
    def test_assert_expensive_cap_is_noop_even_when_over_model_cap(self) -> None:
        db = MagicMock()
        user = SimpleNamespace(id=153, role="user")
        with patch(
            "app.services.cost_control.plan_margin.monthly_expensive_credits_used",
            return_value=45,
        ):
            # Pro premium_llm model cap is 80; 45+45 would have blocked before.
            assert_expensive_feature_monthly_cap(
                db,
                user,
                category="premium_llm",
                extra_credits=45,
                plan_slug="pro",
            )

    def test_pro_with_3329_credits_article_45_allowed(self) -> None:
        db = MagicMock()
        user = SimpleNamespace(id=153, role="user", is_admin=False, api_access_enabled=False)
        with patch("app.services.content_ai_credit_service.credits_enforced", return_value=True):
            with patch("app.services.content_ai_credit_service.get_available_balance", return_value=3329):
                with patch("app.services.content_ai_credit_service.is_admin", return_value=False):
                    with patch(
                        "app.services.content_ai_credit_service.admin_skips_credit_deduction",
                        return_value=False,
                    ):
                        q = quote_content_ai_write(
                            db, user, field="content", word_count=2000, use_system_llm=True
                        )
        self.assertEqual(q["credit_cost"], 45)
        self.assertTrue(q["sufficient_credits"])
        self.assertTrue(q["can_proceed"])

        patches = [patch(t, **kw) for t, kw in _GATE_SAFE]
        for p in patches:
            p.start()
        try:
            with patch("app.services.cost_control.gate.cost_control_enforced", return_value=True):
                with patch("app.services.cost_control.gate.is_admin", return_value=False):
                    with patch("app.services.cost_control.gate.credits_enforced", return_value=True):
                        with patch(
                            "app.services.cost_control.gate.ensure_sufficient_credits",
                            return_value=(3329, True),
                        ):
                            req = CostGateRequest(
                                db=db,
                                user=user,
                                provider=ExternalApiProvider.OPENAI,
                                action="write",
                                credit_cost=45,
                                feature_key="content_ai_article",
                                require_paid_plan=True,
                            )
                            with cost_gate_session(req) as session:
                                self.assertEqual(session.credit_required, 45)
                                self.assertEqual(session.plan_slug, "pro")
        finally:
            for p in reversed(patches):
                p.stop()

    def test_pro_44_credits_article_45_blocks_insufficient(self) -> None:
        db = MagicMock()
        user = SimpleNamespace(id=153, role="user")
        patches = [patch(t, **kw) for t, kw in _GATE_SAFE]
        for p in patches:
            p.start()
        try:
            with patch("app.services.cost_control.gate.cost_control_enforced", return_value=True):
                with patch("app.services.cost_control.gate.is_admin", return_value=False):
                    with patch("app.services.cost_control.gate.credits_enforced", return_value=True):
                        with patch(
                            "app.services.cost_control.gate.ensure_sufficient_credits",
                            return_value=(44, False),
                        ):
                            req = CostGateRequest(
                                db=db,
                                user=user,
                                provider=ExternalApiProvider.OPENAI,
                                action="write",
                                credit_cost=45,
                                feature_key="content_ai_article",
                                require_paid_plan=True,
                            )
                            with self.assertRaises(HTTPException) as ctx:
                                with cost_gate_session(req):
                                    pass
            self.assertEqual(ctx.exception.status_code, 402)
            detail = ctx.exception.detail
            self.assertEqual(detail["code"], "insufficient_credits")
            self.assertNotIn("premium", str(detail.get("message", "")).lower())
            self.assertNotIn("hard cap", str(detail.get("message", "")).lower())
            self.assertIn("45", detail["message"])
            self.assertIn("44", detail["message"])
        finally:
            for p in reversed(patches):
                p.stop()

    def test_basic_blocked_on_premium_feature_entitlement(self) -> None:
        # Basic (starter) does not get kw_advanced — entitlement, not credit/cap.
        self.assertFalse(plan_feature("starter", "kw_advanced", False))
        self.assertTrue(plan_feature("pro", "kw_advanced", False))

        from app.services.dataforseo_billing_service import assert_dataforseo_live_allowed

        db = MagicMock()
        user = SimpleNamespace(id=1, role="user")
        with patch(
            "app.services.dataforseo_billing_service.resolve_cau_ai_plan_slug",
            return_value="starter",
        ):
            with patch("app.services.dataforseo_billing_service.is_admin", return_value=False):
                with self.assertRaises(HTTPException) as ctx:
                    assert_dataforseo_live_allowed(db, user)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail["code"], "kw_basic_only")


class AccountingSsotTests(unittest.TestCase):
    def test_content_ai_reserve_uses_tier_ledger_not_saas_gate_reserve(self) -> None:
        db = MagicMock()
        user = SimpleNamespace(id=153, role="user", is_admin=False, api_access_enabled=False)
        quote = {
            "charge_credits": True,
            "credit_cost": 45,
            "request_id": "bulk:job:1",
            "module": "content_ai",
            "action": "article_long",
            "tier_action": "article_long",
            "lines": [],
            "flags": {},
        }
        captured: dict = {}

        def _fake_reserve(**kwargs):
            captured.update(kwargs)
            return {
                "reservation_id": 99,
                "amount": 45,
                "status": "reserved",
                "already_committed": False,
                "balance_after": 3284,
            }

        with patch("app.services.content_ai_credit_service.credits_enforced", return_value=True):
            with patch(
                "app.services.content_ai_credit_service.admin_skips_credit_deduction",
                return_value=False,
            ):
                with patch(
                    "app.services.content_ai_credit_service.reserve_credits",
                    side_effect=lambda *a, **k: _fake_reserve(**k),
                ):
                    hold = reserve_content_ai_write(
                        db, user, quote, field="content", feature_code="content_ai_article"
                    )
        self.assertIsNotNone(hold)
        self.assertEqual(captured.get("module"), "content_ai")
        self.assertEqual(captured.get("action"), "article_long")
        self.assertNotEqual(captured.get("module"), "saas_gate")

    def test_retry_idempotent_reserve_no_double_charge(self) -> None:
        from app.services.credits import reserve_credits

        calls = {"n": 0}

        def _consume(*args, **kwargs):
            calls["n"] += 1
            return 100

        existing = SimpleNamespace(
            id=7,
            amount=45,
            status="reserved",
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.one_or_none.return_value = existing
        with patch("app.services.credits.consume_credits", side_effect=_consume):
            with patch("app.services.credits.get_available_balance", return_value=100):
                r1 = reserve_credits(
                    db,
                    user_id=153,
                    amount=45,
                    feature_code="content_ai_article",
                    job_id="bulk:job:1",
                    idempotency_key="content_ai_write:bulk:job:1",
                    module="content_ai",
                    action="article_long",
                )
                r2 = reserve_credits(
                    db,
                    user_id=153,
                    amount=45,
                    feature_code="content_ai_article",
                    job_id="bulk:job:1",
                    idempotency_key="content_ai_write:bulk:job:1",
                    module="content_ai",
                    action="article_long",
                )
        self.assertEqual(r1["reservation_id"], 7)
        self.assertEqual(r2["reservation_id"], 7)
        self.assertEqual(calls["n"], 0)  # existing reserved → no second debit


if __name__ == "__main__":
    unittest.main()
