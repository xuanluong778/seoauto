"""
Regression checklist — pricing, quota, credit guards.

Mỗi test_* map 1 dòng trong tests/PRICING_QUOTA_CREDIT_CHECKLIST.md.
Chạy: .venv/bin/python3 -m pytest tests/test_pricing_quota_credit_checklist.py -v
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services.chatbot_cskh_credits import assert_can_consume_reply, record_cskh_ai_reply
from app.services.content_ai_credit_service import quote_content_ai_write
from app.services.cost_control import CostGateRequest, cost_gate_session, execute_guarded_external
from app.services.cost_control.executor import CostControlBypassError
from app.services.cost_control.types import ExternalApiProvider
from app.services.credits import quote_lead_basic_scan, quote_lead_detail
from app.services.dataforseo_billing_service import preview_research_billing
from app.services.saas_economics_service import build_economics_dashboard, provider_for_ledger
from app.services.usage_tracking_service import record_successful_usage

ROOT = Path(__file__).resolve().parents[1]


# ── 01–02: Gate credit / quota trước API ngoài ─────────────────────────────


class TestCheck01InsufficientCreditBlocksExternalApi:
    """User thiếu credit → không gọi API ngoài."""

    def test_cost_gate_blocks_before_http(self) -> None:
        db = MagicMock()
        user = MagicMock(id=42, role="user")
        with patch("app.services.cost_control.gate.cost_control_enforced", return_value=True):
            with patch("app.services.cost_control.gate.is_admin", return_value=False):
                with patch("app.services.cost_control.gate.resolve_cau_ai_plan_slug", return_value="pro"):
                    with patch("app.services.cost_control.gate.credits_enforced", return_value=True):
                        with patch("app.services.saas_economics_guard.assert_expensive_api_allowed"):
                            with patch(
                                "app.services.cost_control.gate.ensure_sufficient_credits",
                                return_value=(3, False),
                            ):
                                with patch("app.services.cost_control.executor.requests.post") as mock_post:
                                    req = CostGateRequest(
                                        db=db,
                                        user=user,
                                        provider=ExternalApiProvider.DATAFORSEO,
                                        action="research_run",
                                        credit_cost=30,
                                    )
                                    with pytest.raises(HTTPException) as exc:
                                        with cost_gate_session(req):
                                            execute_guarded_external(
                                                ExternalApiProvider.DATAFORSEO,
                                                "research_run",
                                                lambda: mock_post("https://api.dataforseo.com"),
                                            )
                                    assert exc.value.status_code == 402
                                    mock_post.assert_not_called()


class TestCheck02QuotaExceededBlocksExternalApi:
    """User vượt quota → không gọi API ngoài."""

    def test_quota_gate_blocks_before_http(self) -> None:
        db = MagicMock()
        user = MagicMock(id=7, role="user")
        with patch("app.services.cost_control.gate.cost_control_enforced", return_value=True):
            with patch("app.services.cost_control.gate.is_admin", return_value=False):
                with patch("app.services.cost_control.gate.resolve_cau_ai_plan_slug", return_value="pro"):
                    with patch("app.services.cost_control.gate.credits_enforced", return_value=True):
                        with patch(
                            "app.services.cost_control.gate.ensure_sufficient_credits",
                            return_value=(500, True),
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
                                        action="place_search",
                                        credit_cost=12,
                                        feature_key="lead_scan",
                                        quota_units=1,
                                    )
                                    with pytest.raises(HTTPException) as exc:
                                        with cost_gate_session(req):
                                            execute_guarded_external(
                                                ExternalApiProvider.GOOGLE_PLACES,
                                                "place_search",
                                                lambda: mock_get("https://maps.googleapis.com"),
                                            )
        assert exc.value.status_code == 429
        detail = exc.value.detail
        assert isinstance(detail, dict)
        assert detail.get("code") == "quota_exceeded"
        mock_get.assert_not_called()


# ── 03: UI billing không gọi API đắt ───────────────────────────────────────


class TestCheck03BillingUiUsesInternalApisOnly:
    """Mở/đổi tab account-billing chỉ gọi API nội bộ."""

    FORBIDDEN_URL_PATTERNS = (
        r"dataforseo",
        r"googleapis\.com",
        r"openai\.com",
        r"api\.anthropic",
        r"places\.google",
    )

    def test_account_billing_js_fetch_targets(self) -> None:
        js = (ROOT / "static/js/account-billing.js").read_text(encoding="utf-8")
        paths = re.findall(r'(?:apiGet|fetch)\s*\(\s*["\']([^"\']+)["\']', js)
        assert paths, "Không tìm thấy fetch/apiGet trong account-billing.js"
        for path in paths:
            low = path.lower()
            assert low.startswith("/") or low.startswith("http"), path
            for bad in self.FORBIDDEN_URL_PATTERNS:
                assert not re.search(bad, low), f"URL đắt trong billing UI: {path}"
            if path.startswith("/api/"):
                assert "saas" in path or "admin" in path or path.startswith("/auth"), path

    def test_credit_confirm_preview_is_internal(self) -> None:
        js = (ROOT / "static/js/digiseo-credit-confirm.js").read_text(encoding="utf-8")
        assert 'PREVIEW_API = "/api/credits/preview"' in js
        assert "dataforseo" not in js.lower()


# ── 04: Idempotency — bấm nhiều lần 1 request thật (quota event) ─────────────


class TestCheck04IdempotentUsageRecording:
    """Cùng idempotency_key → không ghi usage 2 lần."""

    def test_duplicate_idempotency_key_returns_same_event(self) -> None:
        import app.models.knowledge  # noqa: F401
        import app.models.monthly_usage  # noqa: F401
        import app.models.seo  # noqa: F401
        import app.models.usage_event  # noqa: F401
        import app.models.user  # noqa: F401

        from app.core.security import hash_password
        from app.db import Base
        from app.models.user import User
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        db = sessionmaker(bind=engine)()
        user = User(email="idem@test.com", password_hash=hash_password("x"), has_password=True)
        db.add(user)
        db.commit()

        key = "test-action:job-abc"
        e1 = record_successful_usage(
            db, user.id, "content_ai_article", quantity=1, idempotency_key=key
        )
        db.commit()
        e2 = record_successful_usage(
            db, user.id, "content_ai_article", quantity=1, idempotency_key=key
        )
        db.commit()
        assert e1.id == e2.id
        db.close()


# ── 05: Cache không phát sinh chi phí API ────────────────────────────────────


class TestCheck05CacheSkipsExternalApiAndCost:
    """Cache hit → không HTTP ngoài; credit giảm hoặc = 0."""

    def test_lead_scan_cache_zero_credit(self) -> None:
        q = quote_lead_basic_scan(mode="keyword", limit=100, from_cache=True)
        assert q["credit_required"] == 0
        assert q["from_cache"] == 1

    def test_cost_gate_cache_hit_raises_bypass(self) -> None:
        db = MagicMock()
        user = MagicMock(id=3)
        cached = {"items": []}
        with patch("app.services.cost_control.executor.requests.post") as mock_post:
            req = CostGateRequest(
                db=db,
                user=user,
                provider=ExternalApiProvider.DATAFORSEO,
                action="search_volume",
                credit_cost=99,
                cache_lookup=lambda: cached,
            )
            with cost_gate_session(req) as session:
                assert session.cache_hit is True
                with pytest.raises(CostControlBypassError):
                    execute_guarded_external(
                        ExternalApiProvider.DATAFORSEO,
                        "search_volume",
                        lambda: mock_post("https://api.dataforseo.com"),
                    )
        mock_post.assert_not_called()

    @patch("app.services.dataforseo_billing_service.is_admin", return_value=False)
    @patch("app.services.dataforseo_billing_service.resolve_cau_ai_plan_slug", return_value="pro")
    @patch("app.services.dataforseo_billing_service.plan_feature", return_value=True)
    @patch(
        "app.services.keyword_dataforseo_expand.peek_k4k_cache_status",
        return_value={"hits": 1, "misses": 0, "total": 1},
    )
    def test_dataforseo_full_cache_reduces_credit(self, _k4k, _feat, _slug, _admin) -> None:
        preview = preview_research_billing(
            MagicMock(), SimpleNamespace(id=1), seeds=["seo"], country="vn", language="vi"
        )
        assert preview.cache_hit is True
        assert preview.api_mode == "cache"
        assert preview.k4k_api_tasks == 0
        assert preview.credit_cost <= 5


# ── 06: Lead Scanner 100 SĐT ─────────────────────────────────────────────────


class TestCheck06LeadScanner100PhonesCreditRange:
    """100 lead + lấy SĐT → ~1000–1200 credit theo registry (11/detail + scan pages)."""

    def test_100_leads_with_details_in_config_range(self) -> None:
        basic = quote_lead_basic_scan(mode="keyword", limit=100, from_cache=False)
        detail = quote_lead_detail(100)
        total = basic["credit_required"] + detail["credit_required"]
        per_detail = detail["detail_cost"] // detail["detail_calls"]
        assert per_detail == 11
        assert basic["search_pages"] == 5
        assert 1000 <= total <= 1200, f"total={total}, basic={basic}, detail={detail}"


# ── 07: Keyword DataForSEO credit ────────────────────────────────────────────


class TestCheck07KeywordResearchDataforseoCredits:
    @patch("app.services.dataforseo_billing_service.is_admin", return_value=False)
    @patch("app.services.dataforseo_billing_service.resolve_cau_ai_plan_slug", return_value="starter")
    @patch("app.services.dataforseo_billing_service.plan_feature", return_value=False)
    def test_basic_plan_cache_mode_5_credit(self, _f, _s, _a) -> None:
        p = preview_research_billing(
            MagicMock(), SimpleNamespace(id=2), seeds=["a"], country="vn", language="vi"
        )
        assert p.api_mode == "basic"
        assert p.credit_cost == 5

    @patch("app.services.dataforseo_billing_service.is_admin", return_value=False)
    @patch("app.services.dataforseo_billing_service.resolve_cau_ai_plan_slug", return_value="pro")
    @patch("app.services.dataforseo_billing_service.plan_feature", return_value=True)
    @patch(
        "app.services.keyword_dataforseo_expand.peek_k4k_cache_status",
        return_value={"hits": 0, "misses": 1, "total": 1},
    )
    def test_pro_live_30_credit(self, _k, _f, _s, _a) -> None:
        p = preview_research_billing(
            MagicMock(), SimpleNamespace(id=3), seeds=["a"], country="vn", language="vi"
        )
        assert p.api_mode == "live"
        assert p.credit_cost == 30


# ── 08: Content AI theo số từ ───────────────────────────────────────────────


class TestCheck08ContentAiWordCountTiers:
    @patch("app.services.content_ai_credit_service.credits_enforced", return_value=True)
    @patch("app.services.content_ai_credit_service.get_available_balance", return_value=999)
    @patch("app.services.content_ai_credit_service.is_admin", return_value=False)
    @patch("app.services.content_ai_credit_service.api_access_enabled_for", return_value=False)
    def test_tiers_12_25_45(self, *_mocks) -> None:
        user = SimpleNamespace(id=1)
        db = MagicMock()
        q_s = quote_content_ai_write(db, user, field="content", word_count=900, use_system_llm=True)
        q_m = quote_content_ai_write(db, user, field="content", word_count=1500, use_system_llm=True)
        q_l = quote_content_ai_write(db, user, field="content", word_count=2000, use_system_llm=True)
        assert (q_s["credit_cost"], q_m["credit_cost"], q_l["credit_cost"]) == (12, 25, 45)


# ── 09: Chatbot vượt quota → trừ credit ─────────────────────────────────────


class TestCheck09ChatbotOverageUsesMainCredit:
    def test_overage_billing_mode_and_cost(self) -> None:
        db = MagicMock()
        user_id = 99
        plan_slug = "starter"
        with patch(
            "app.services.chatbot_cskh_credits.build_usage_snapshot",
            return_value={
                "allowed": False,
                "remaining": 0,
                "effective_limit": 500,
                "ai_replies_used": 500,
            },
        ):
            with patch("app.services.credits.credits_enforced", return_value=True):
                with patch("app.services.credits.cost_chatbot_cskh_reply", return_value=2):
                    with patch("app.services.credits.ensure_sufficient_credits", return_value=(50, True)):
                        out = assert_can_consume_reply(db, user_id, plan_slug)
        assert out["billing"] == "main_credit"
        assert out["overage_cost"] == 2

    def test_record_overage_consumes_credits(self) -> None:
        db = MagicMock()
        with patch(
            "app.services.chatbot_cskh_credits.build_usage_snapshot",
            return_value={"allowed": False},
        ):
            with patch("app.services.credits.credits_enforced", return_value=True):
                with patch("app.services.credits.cost_chatbot_cskh_reply", return_value=2):
                    with patch("app.services.credits.consume_credits") as consume:
                        with patch("app.services.chatbot_cskh_credits.increment_reply_usage"):
                            meta = record_cskh_ai_reply(db, user_id=5, bot_id=1, plan_slug="pro")
        consume.assert_called_once()
        assert meta["credit_charged"] == 2
        assert meta["overage"] is True


# ── 10: Admin economics theo module ─────────────────────────────────────────


class TestCheck10AdminEconomicsModuleBurn:
    def test_provider_mapping_and_dashboard_has_burn(self) -> None:
        assert provider_for_ledger(module="keyword", action="research_run", reason=None) == "dataforseo"
        assert provider_for_ledger(module="content_ai", action="article_medium", reason=None) == "openai"

    def test_dashboard_structure(self) -> None:
        db = MagicMock()
        with patch("app.services.saas_economics_service.load_economics_settings", return_value={}):
            with patch(
                "app.services.saas_economics_service.get_economics_state",
                return_value=SimpleNamespace(expensive_api_blocked=False, block_reason=None, blocked_at=None),
            ):
                with patch(
                    "app.services.saas_economics_service._aggregate_burn",
                    return_value={
                        "credits": 120,
                        "estimated_cost_vnd": 50000,
                        "by_provider": {},
                        "by_module": {"keyword": 120},
                        "by_action": {},
                        "by_user_raw": {},
                    },
                ):
                    with patch(
                        "app.services.saas_economics_service._aggregate_revenue",
                        return_value={"total_base_vnd": 0, "subscription_gross_vnd": 0, "credit_pack_gross_vnd": 0},
                    ):
                        with patch("app.services.saas_economics_service._build_at_risk_users", return_value=[]):
                            with patch("app.services.saas_economics_service._build_alerts", return_value=[]):
                                dash = build_economics_dashboard(db)
        assert dash["credit_burn"]["month"] == 120
        assert dash["by_module"]["month"]["keyword"] == 120


# ── 11: SePay kích hoạt gói ─────────────────────────────────────────────────


class TestCheck11SepayActivationImports:
    """Smoke — module activation tồn tại và test chi tiết ở test_payment_activation.py."""

    def test_activation_service_exports(self) -> None:
        from app.services.payment_activation_service import activate_product, ProductActivationError

        assert callable(activate_product)
        assert ProductActivationError is not None


# ── 12: Các module khác không bị ảnh hưởng (import smoke) ───────────────────


class TestCheck12CoreModulesImportable:
    """Router/service chính vẫn import được sau thay đổi billing."""

    @pytest.mark.parametrize(
        "module_path",
        [
            "app.routers.analyze",
            "app.routers.pages",
            "app.routers.keywords",
            "app.routers.content_auto_update",
            "app.routers.index_control",
            "app.services.google_map_lead_scanner_service",
            "app.services.chatbot_cskh_ai_service",
        ],
    )
    def test_import(self, module_path: str) -> None:
        import importlib

        mod = importlib.import_module(module_path)
        assert mod is not None
