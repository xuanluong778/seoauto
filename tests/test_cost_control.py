"""Tests for centralized external API cost control."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.services.cost_control import (
    CostGateRequest,
    ExternalApiProvider,
    cost_control_enforced,
    cost_gate_session,
    execute_guarded_external,
)
from app.services.cost_control.executor import CostControlBypassError
from app.services.cost_control.retry import retry_external_call

_SOFTWARE_ACCESS_PATCH = "app.services.cost_control.gate.user_has_software_access"
_GATE_SIDE_PATCHES = (
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


class CostControlGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._sw = patch(_SOFTWARE_ACCESS_PATCH, return_value=True)
        self._sw.start()
        self._side = [patch(target, **kwargs) for target, kwargs in _GATE_SIDE_PATCHES]
        for p in self._side:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self._side):
            p.stop()
        self._sw.stop()

    def test_insufficient_credit_blocks_before_external_api(self) -> None:
        db = MagicMock()
        user = MagicMock()
        user.id = 42
        user.role = "user"

        with patch("app.services.cost_control.gate.cost_control_enforced", return_value=True):
            with patch("app.services.cost_control.gate.is_admin", return_value=False):
                with patch("app.services.cost_control.gate.resolve_cau_ai_plan_slug", return_value="pro"):
                    with patch("app.services.cost_control.gate.credits_enforced", return_value=True):
                        with patch(
                            "app.services.cost_control.gate.ensure_sufficient_credits",
                            return_value=(5, False),
                        ):
                            with patch("app.services.cost_control.executor.requests.post") as mock_post:
                                req = CostGateRequest(
                                    db=db,
                                    user=user,
                                    provider=ExternalApiProvider.DATAFORSEO,
                                    action="search_volume",
                                    credit_cost=10,
                                )
                                with self.assertRaises(HTTPException) as ctx:
                                    with cost_gate_session(req):
                                        execute_guarded_external(
                                            ExternalApiProvider.DATAFORSEO,
                                            "search_volume",
                                            lambda: mock_post("https://api.example.com"),
                                        )
        self.assertEqual(ctx.exception.status_code, 402)
        mock_post.assert_not_called()

    def test_quota_exceeded_blocks_before_external_api(self) -> None:
        db = MagicMock()
        user = MagicMock()
        user.id = 7
        user.role = "user"

        with patch("app.services.cost_control.gate.cost_control_enforced", return_value=True):
            with patch("app.services.cost_control.gate.is_admin", return_value=False):
                with patch("app.services.cost_control.gate.resolve_cau_ai_plan_slug", return_value="pro"):
                    with patch("app.services.cost_control.gate.credits_enforced", return_value=True):
                        with patch(
                            "app.services.cost_control.gate.ensure_sufficient_credits",
                            return_value=(100, True),
                        ):
                            with patch(
                                "app.services.cost_control.gate.usage_tracking_service.get_quota_remaining",
                                return_value=0,
                            ):
                                with patch("app.services.cost_control.executor.requests.get") as mock_get:
                                    req = CostGateRequest(
                                        db=db,
                                        user=user,
                                        provider=ExternalApiProvider.GOOGLE_PLACES,
                                        action="geocode",
                                        credit_cost=1,
                                        feature_key="lead_scan",
                                        quota_units=1,
                                    )
                                    with self.assertRaises(HTTPException) as ctx:
                                        with cost_gate_session(req):
                                            execute_guarded_external(
                                                ExternalApiProvider.GOOGLE_PLACES,
                                                "geocode",
                                                lambda: mock_get("https://maps.example.com"),
                                            )
        self.assertEqual(ctx.exception.status_code, 429)
        detail = ctx.exception.detail
        self.assertIsInstance(detail, dict)
        self.assertEqual(detail.get("code"), "quota_exceeded")
        mock_get.assert_not_called()

    def test_cache_hit_skips_external_api(self) -> None:
        db = MagicMock()
        user = MagicMock()
        user.id = 3

        cached_payload = {"ok": True, "from": "cache"}

        with patch("app.services.cost_control.executor.requests.post") as mock_post:
            req = CostGateRequest(
                db=db,
                user=user,
                provider=ExternalApiProvider.DATAFORSEO,
                action="search_volume",
                credit_cost=99,
                cache_lookup=lambda: cached_payload,
            )
            with cost_gate_session(req) as session:
                self.assertTrue(session.cache_hit)
                self.assertEqual(session.cached_value, cached_payload)
                with self.assertRaises(CostControlBypassError):
                    execute_guarded_external(
                        ExternalApiProvider.DATAFORSEO,
                        "search_volume",
                        lambda: mock_post("https://api.example.com"),
                    )
        mock_post.assert_not_called()

    def test_retry_external_call_max_two_retries(self) -> None:
        calls = {"n": 0}

        def always_fails() -> str:
            calls["n"] += 1
            raise RuntimeError("transient")

        with patch("app.services.cost_control.retry.external_api_retry_max", return_value=2):
            with patch("app.services.cost_control.retry.time.sleep"):
                with self.assertRaises(RuntimeError):
                    retry_external_call(always_fails, is_retryable=lambda _e: True)
        self.assertEqual(calls["n"], 3)

    def test_missing_gate_blocks_when_enforced(self) -> None:
        with patch("app.services.cost_control.executor.cost_control_enforced", return_value=True):
            with patch("app.services.cost_control.executor.get_active_cost_gate", return_value=None):
                with self.assertRaises(CostControlBypassError):
                    execute_guarded_external(
                        ExternalApiProvider.OPENAI,
                        "chat_completion",
                        lambda: "x",
                    )


class CostControlSettingsTests(unittest.TestCase):
    def test_default_enforced(self) -> None:
        with patch.dict("os.environ", {"COST_CONTROL_ENABLED": "1"}, clear=False):
            self.assertTrue(cost_control_enforced())


class ContentAiCskhGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._sw = patch("app.services.saas_gate.user_has_software_access", return_value=True)
        self._sw.start()
        self._gate_sw = patch(_SOFTWARE_ACCESS_PATCH, return_value=True)
        self._gate_sw.start()
        self._side = [patch(target, **kwargs) for target, kwargs in _GATE_SIDE_PATCHES]
        for p in self._side:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self._side):
            p.stop()
        self._gate_sw.stop()
        self._sw.stop()

    def test_content_ai_llm_gate_blocks_insufficient_credit(self) -> None:
        from app.services.cost_control.module_gates import content_ai_llm_gate

        db = MagicMock()
        user = MagicMock()
        user.id = 7
        user.role = "user"

        with patch("app.services.cost_control.gate.cost_control_enforced", return_value=True):
            with patch("app.services.cost_control.gate.is_admin", return_value=False):
                with patch("app.services.cost_control.gate.resolve_cau_ai_plan_slug", return_value="pro"):
                    with patch("app.services.cost_control.gate.credits_enforced", return_value=True):
                        with patch(
                            "app.services.cost_control.gate.ensure_sufficient_credits",
                            return_value=(1, False),
                        ):
                            with patch(
                                "app.services.content_ai_entitlement.bypass_entitlement",
                                return_value=False,
                            ):
                                with self.assertRaises(HTTPException) as ctx:
                                    with content_ai_llm_gate(
                                        db,
                                        user,
                                        action="suggest",
                                        field="content",
                                        use_system_llm=True,
                                        llm_cfg=None,
                                    ):
                                        pass
        self.assertEqual(ctx.exception.status_code, 402)

    def test_chatbot_cskh_llm_gate_blocks_quota_exceeded(self) -> None:
        from app.services.cost_control.module_gates import chatbot_cskh_llm_gate

        db = MagicMock()
        owner = MagicMock()
        owner.id = 9
        owner.role = "user"

        with patch("app.services.cost_control.gate.cost_control_enforced", return_value=True):
            with patch("app.services.cost_control.gate.is_admin", return_value=False):
                with patch(
                    "app.services.cau_ai_fix_entitlement.resolve_cau_ai_plan_slug",
                    return_value="basic",
                ):
                    with patch(
                        "app.services.chatbot_cskh_credits.assert_can_consume_reply",
                        side_effect=HTTPException(status_code=429, detail="quota"),
                    ):
                        with self.assertRaises(HTTPException) as ctx:
                            with chatbot_cskh_llm_gate(
                                db,
                                owner,
                                action="widget_reply",
                                bot_id=1,
                            ):
                                pass
        self.assertEqual(ctx.exception.status_code, 429)


if __name__ == "__main__":
    unittest.main()
