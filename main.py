from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / "env.local")

from app.services.site_seo import install_jinja_seo_globals

install_jinja_seo_globals()

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy.orm import Session
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.auth import router as auth_router
from app.api.projects import router as projects_router
from sqlalchemy import inspect, text

from app.db import Base, engine, get_db
from app.models import seo  # noqa: F401
from app.models.crawl_job import DistributedCrawlJob, DistributedCrawlResult  # noqa: F401
from app.models.keyword_intel import (  # noqa: F401
    SEOKeywordClusterEntity,
    SEOKeywordEntity,
    SEOKeywordUrlMapping,
)
from app.models.keyword_research_project import KeywordResearchProject  # noqa: F401
from app.models.keyword_cluster_job import KeywordClusterJob  # noqa: F401
from app.models.content_ai_publish_schedule import ContentAIPublishSchedule  # noqa: F401
from app.models.index_control import IndexControlCheck, IndexControlCheckItem, IndexNowSubmit, IndexNowSubmitLog  # noqa: F401
from app.models.keyword_cluster_project import KeywordClusterProject  # noqa: F401
from app.models.keyword_volume_cache import KeywordVolumeCache  # noqa: F401
from app.models.dataforseo_usage_log import DataforseoUsageLog  # noqa: F401
from app.models.otp_login import OtpLogin  # noqa: F401
from app.models.credit_ledger import CreditLedger  # noqa: F401
from app.models.credit_ledger_entry import CreditLedgerEntry  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.security_audit_log import SecurityAuditLog  # noqa: F401
from app.models.user_api_key import UserApiKey  # noqa: F401
from app.models.user_trial import TrialKeyClaim, UserTrial  # noqa: F401
from app.models.saas_trial import SaasTrialClaim, SaasTrialDailyUsage  # noqa: F401
from app.models.plan import Plan  # noqa: F401 — SaaS Phase 1
from app.models.subscription import Subscription  # noqa: F401
from app.models.usage_limit import UsageLimit  # noqa: F401
from app.models.usage_event import UsageEvent  # noqa: F401
from app.models.monthly_usage import MonthlyUsage  # noqa: F401
from app.models.payment_transaction import PaymentTransaction  # noqa: F401
from app.models.platform_integration import PlatformIntegration  # noqa: F401
from app.models.sepay_payment_transaction import SepayPaymentTransaction  # noqa: F401
from app.models.user_quota_addon import UserQuotaAddon  # noqa: F401
from app.models.affiliate import (  # noqa: F401
    AffiliateAccount,
    AffiliateClick,
    AffiliateCommission,
    AffiliatePayout,
    AffiliateReferral,
    AffiliateSettings,
)
from app.models import knowledge as knowledge_models  # noqa: F401
from app.routers.analyze import router as analyze_router
from app.routers.seo_score import router as seo_score_router
from app.routers.internal_links import router as internal_links_router
from app.routers.pages import pricing_page as saas_pricing_page
from app.routers.pages import router as pages_router
from app.routers.report import router as report_router
from app.routers.settings_api import router as settings_api_router
from app.routers.integrations_google import router as integrations_router
from app.routers.serp_intel import router as serp_intel_router
from app.routers.keyword_intelligence import router as keyword_intel_router
from app.routers.schema import router as schema_router
from app.routers.keywords import router as keywords_router
from app.routers.wp_bulk_update import router as wp_bulk_router
from app.routers.user_files import router as user_files_router
from app.routers.admin import _admin_page_user
from app.routers.admin import api_router as admin_api_router
from app.routers.admin import router as admin_router
from app.routers.saas_admin import router as saas_admin_router
from app.routers.saas import router as saas_router
from app.routers.trial_api import router as trial_api_router
from app.routers.payments import router as payments_router
from app.routers.chatbot import router as chatbot_router
from app.routers.rank_tracking import router as rank_tracking_router
from app.routers.social_auto import router as social_auto_router
from app.routers.index_control import router as index_control_router
from app.routers.social_auto_web20 import router as social_auto_web20_router
from app.routers.social_auto_web20 import blogger_integrations_router as social_auto_blogger_integrations_router
from app.routers.content_auto_update import router as content_auto_update_router
from app.routers.content_ai_bulk_images import router as content_ai_bulk_images_router
from app.routers.content_ai_bulk_publish import router as content_ai_bulk_publish_router
from app.routers.affiliate import router as affiliate_router, set_referral_cookies
from app.routers.admin_affiliate import router as admin_affiliate_router
from app.routers.admin_billing import router as admin_billing_router
from app.routers.admin_backup import router as admin_backup_router
from app.routers.admin_integrations import router as admin_integrations_router
from app.routers.admin_lead_scanner import router as admin_lead_scanner_router
from app.routers.admin_saas_economics import router as admin_saas_economics_router
from app.routers.credits_preview import router as credits_preview_router
from app.routers.wordpress_plugin import router as wordpress_plugin_router
from app.routers.chatbot_cskh import router as chatbot_cskh_router
from app.routers.chatbot_cskh_platform import router as chatbot_cskh_platform_router
from app.routers.chatbot_cskh_inbox import router as chatbot_cskh_inbox_router
from app.routers.chatbot_cskh_knowledge import router as chatbot_cskh_knowledge_router
from app.routers.chatbot_cskh_kb import router as chatbot_cskh_kb_router
from app.routers.chatbot_cskh_facebook import router as chatbot_cskh_facebook_router
from app.routers.chatbot_cskh_public import router as chatbot_cskh_public_router
from app.routers.google_map_seo import router as google_map_seo_router
from app.routers.seo_public import router as seo_public_router
from app.services.internal_linking import models as il_models  # noqa: F401
from app.core.runtime import allowed_hosts, cors_allowed_origins, is_production
from app.middleware.security import SecurityMiddleware
from app.middleware.chatbot_public_cors import ChatbotPublicCorsMiddleware
from app.services.safe_errors import global_exception_handler


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    from app.db import SessionLocal
    from app.services.affiliate_service import migrate_legacy_affiliate_accounts
    from app.services.seoauto_pricing_catalog import ensure_billing_catalog_sync
    from app.services.content_ai_bulk_worker_loop import start_content_ai_bulk_worker_background
    from app.services.content_ai_publish_worker_loop import start_content_ai_publish_worker_background
    from app.services.payment_config import log_payment_config_status
    from app.services.saas_runtime_guard import log_saas_runtime_guard

    log_payment_config_status()
    log_saas_runtime_guard()

    db = SessionLocal()
    try:
        migrate_legacy_affiliate_accounts(db)
        ensure_billing_catalog_sync(db)
        db.commit()
    finally:
        db.close()

    start_content_ai_bulk_worker_background()
    start_content_ai_publish_worker_background()
    yield


_prod = is_production()
app = FastAPI(
    title="Seoauto API",
    version="1.0.0",
    lifespan=_app_lifespan,
    docs_url=None if _prod else "/docs",
    redoc_url=None if _prod else "/redoc",
    openapi_url=None if _prod else "/openapi.json",
)
app.add_exception_handler(HTTPException, global_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

_cors = cors_allowed_origins()
if _cors:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    )

_hosts = allowed_hosts()
if _prod and _hosts and _hosts != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_hosts)

app.add_middleware(SecurityMiddleware)
app.add_middleware(ChatbotPublicCorsMiddleware)


@app.middleware("http")
async def bind_request_user_context(request: Request, call_next):
    """Attach logged-in user id so LLM/API-key resolution is per-user."""
    from app.core.user_context import bind_request_user_id, unbind_request_user_id
    from app.db import SessionLocal
    from app.services.auth import user_from_token

    uid: int | None = None
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            db = SessionLocal()
            try:
                uid = user_from_token(db, token).id
            except Exception:
                uid = None
            finally:
                db.close()

    ref_code = (request.query_params.get("ref") or "").strip()
    path = request.url.path or ""
    skip_ref_redirect = (
        "/static",
        "/affiliate/",
        "/admin/api",
        "/api/",
    )
    should_strip_ref = (
        ref_code
        and request.method == "GET"
        and not any(path.startswith(p) for p in skip_ref_redirect)
    )

    ctx_token = bind_request_user_id(uid)
    try:
        if should_strip_ref:
            from app.services.affiliate_service import track_click

            clean_url = str(request.url.remove_query_params("ref"))
            response = RedirectResponse(url=clean_url, status_code=302)
            db = SessionLocal()
            try:
                result = track_click(db, referral_code=ref_code, request=request)
                if result:
                    db.commit()
                    set_referral_cookies(response, result, request=request)
            except Exception:
                db.rollback()
            finally:
                db.close()
            return response

        response = await call_next(request)
    finally:
        unbind_request_user_id(ctx_token)

    return response


app.include_router(settings_api_router)
_static_dir = Path(__file__).resolve().parent / "static"
if _static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
app.include_router(analyze_router)
app.include_router(seo_score_router, prefix="/api")
app.include_router(seo_public_router)
app.include_router(pages_router)
app.include_router(report_router)
app.include_router(integrations_router)
app.include_router(serp_intel_router)
app.include_router(keyword_intel_router)
app.include_router(schema_router)
app.include_router(keywords_router)
app.include_router(wp_bulk_router)
app.include_router(user_files_router)
app.include_router(internal_links_router)
app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(admin_router)
app.include_router(admin_api_router, prefix="/admin/api")
app.include_router(admin_api_router, prefix="/api/admin")  # legacy alias
app.include_router(saas_admin_router, prefix="/admin/api")
app.include_router(saas_admin_router, prefix="/api/admin")
app.include_router(saas_router, prefix="/api")
app.include_router(trial_api_router, prefix="/api")
app.include_router(credits_preview_router, prefix="/api")
app.include_router(wordpress_plugin_router, prefix="/api")
app.include_router(payments_router, prefix="/api")
app.include_router(chatbot_router, prefix="/chatbot")
app.include_router(chatbot_router, prefix="/api/chatbot")
app.include_router(chatbot_cskh_platform_router, prefix="/api/chatbot")
app.include_router(chatbot_cskh_knowledge_router, prefix="/api/chatbot")
app.include_router(chatbot_cskh_kb_router, prefix="/api/chatbot")
app.include_router(chatbot_cskh_inbox_router, prefix="/api/chatbot")
app.include_router(chatbot_cskh_facebook_router, prefix="/api/chatbot")
app.include_router(google_map_seo_router, prefix="/api/google-map-seo")
app.include_router(chatbot_cskh_public_router, prefix="/api/chatbot")
app.include_router(rank_tracking_router, prefix="/api/rank-tracking")
app.include_router(social_auto_router, prefix="/api/social")
app.include_router(social_auto_web20_router, prefix="/api/social")
app.include_router(social_auto_blogger_integrations_router, prefix="/api/integrations")
app.include_router(index_control_router, prefix="/api/index-control")
app.include_router(chatbot_cskh_router, prefix="/api/chatbot-cskh")
app.include_router(content_auto_update_router)
app.include_router(content_ai_bulk_publish_router)
app.include_router(content_ai_bulk_images_router)
app.include_router(affiliate_router)
app.include_router(admin_affiliate_router, prefix="/admin")
app.include_router(admin_affiliate_router, prefix="/admin/api")
app.include_router(admin_affiliate_router, prefix="/api/admin")
app.include_router(admin_billing_router, prefix="/admin/api")
app.include_router(admin_billing_router, prefix="/api/admin")
app.include_router(admin_backup_router, prefix="/admin/api")
app.include_router(admin_backup_router, prefix="/api/admin")
app.include_router(admin_integrations_router, prefix="/admin/api")
app.include_router(admin_integrations_router, prefix="/api/admin")
app.include_router(admin_lead_scanner_router, prefix="/admin/api")
app.include_router(admin_lead_scanner_router, prefix="/api/admin")
app.include_router(admin_saas_economics_router, prefix="/admin/api")
app.include_router(admin_saas_economics_router, prefix="/api/admin")
Base.metadata.create_all(bind=engine)

_templates = Jinja2Templates(directory="templates")


def _ensure_users_has_password_column() -> None:
    insp = inspect(engine)
    if "users" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    if "has_password" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN has_password BOOLEAN NOT NULL DEFAULT true"))


_ensure_users_has_password_column()


def _ensure_user_credit_balance_column() -> None:
    insp = inspect(engine)
    if "users" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    if "credit_balance" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN credit_balance INTEGER NOT NULL DEFAULT 0"))


_ensure_user_credit_balance_column()


def _ensure_knowledge_base_tables() -> None:
    """Additive KB tables only; legacy data/ai_knowledge_bases.json is not modified."""
    from app.knowledge_tables import ensure_knowledge_tables

    ensure_knowledge_tables()


_ensure_knowledge_base_tables()


def _ensure_keyword_history_user_id() -> None:
    insp = inspect(engine)
    for table in ("keyword_research_projects", "keyword_cluster_projects"):
        if table not in insp.get_table_names():
            continue
        cols = {c["name"] for c in insp.get_columns(table)}
        if "user_id" not in cols:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER"))


_ensure_keyword_history_user_id()


def _ensure_user_role_column() -> None:
    import os

    insp = inspect(engine)
    if "users" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    if "role" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(32) NOT NULL DEFAULT 'user'"))
    admin_email = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
    if admin_email:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE users SET role = 'admin' WHERE lower(email) = :email"),
                {"email": admin_email},
            )


_ensure_user_role_column()


def _ensure_user_status_column() -> None:
    insp = inspect(engine)
    if "users" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    if "status" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'active'"))


_ensure_user_status_column()


def _ensure_user_api_access_columns() -> None:
    insp = inspect(engine)
    if "users" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    with engine.begin() as conn:
        if "api_access_enabled" not in cols:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN api_access_enabled BOOLEAN NOT NULL DEFAULT true")
            )
            conn.execute(text("UPDATE users SET api_access_enabled = true"))
        if "use_admin_api_pool" not in cols:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN use_admin_api_pool BOOLEAN NOT NULL DEFAULT false")
            )


_ensure_user_api_access_columns()


def _ensure_user_allow_custom_api_key_column() -> None:
    insp = inspect(engine)
    if "users" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    if "allow_custom_api_key" not in cols:
        with engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN allow_custom_api_key BOOLEAN NOT NULL DEFAULT false")
            )


_ensure_user_allow_custom_api_key_column()


def _ensure_user_free_usage_expires_at_column() -> None:
    insp = inspect(engine)
    if "users" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    if "free_usage_expires_at" not in cols:
        col_type = "TIMESTAMP WITH TIME ZONE" if engine.dialect.name != "sqlite" else "DATETIME"
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE users ADD COLUMN free_usage_expires_at {col_type}"))


_ensure_user_free_usage_expires_at_column()


def _ensure_saas_trial_3d_schema() -> None:
    from app.migrations.ensure_saas_trial_3d import ensure_saas_trial_3d

    ensure_saas_trial_3d()


_ensure_saas_trial_3d_schema()


def _ensure_payment_orders_table() -> None:
    from app.migrations.ensure_payment_orders import ensure_payment_orders_table

    ensure_payment_orders_table()


_ensure_payment_orders_table()


def _ensure_affiliate_schema() -> None:
    from app.migrations.ensure_affiliate_schema import ensure_affiliate_schema

    ensure_affiliate_schema()


_ensure_affiliate_schema()


def _ensure_backup_runs_table() -> None:
    from app.migrations.ensure_backup_runs import ensure_backup_runs_table

    ensure_backup_runs_table()


_ensure_backup_runs_table()


def _ensure_sepay_payment_transactions_table() -> None:
    from app.migrations.ensure_sepay_payment_transactions import ensure_sepay_payment_transactions_table

    ensure_sepay_payment_transactions_table()


_ensure_sepay_payment_transactions_table()


def _ensure_billing_activation_schema() -> None:
    from app.migrations.ensure_billing_activation_schema import ensure_billing_activation_schema

    ensure_billing_activation_schema()


_ensure_billing_activation_schema()


def _ensure_credit_ledger_v3() -> None:
    from app.migrations.ensure_credit_ledger_v3 import ensure_credit_ledger_v3

    ensure_credit_ledger_v3()


_ensure_credit_ledger_v3()


def _reconcile_stale_user_credit_balances() -> None:
    from app.db import SessionLocal
    from app.services.credits import reconcile_stale_credit_balances

    db = SessionLocal()
    try:
        fixed = reconcile_stale_credit_balances(db)
        if fixed:
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


_reconcile_stale_user_credit_balances()


def _ensure_credit_ledger_v2() -> None:
    from app.migrations.ensure_credit_ledger_v2 import ensure_credit_ledger_v2

    ensure_credit_ledger_v2()


_ensure_credit_ledger_v2()


def _ensure_credit_ledger_admin_columns() -> None:
    from app.migrations.ensure_credit_ledger_admin_columns import ensure_credit_ledger_admin_columns

    ensure_credit_ledger_admin_columns()


_ensure_credit_ledger_admin_columns()


def _ensure_credit_ledger_audit_columns() -> None:
    from app.migrations.ensure_credit_ledger_audit_columns import ensure_credit_ledger_audit_columns

    ensure_credit_ledger_audit_columns()


_ensure_credit_ledger_audit_columns()


def _ensure_credit_cost_configs() -> None:
    from app.migrations.ensure_credit_cost_configs import ensure_credit_cost_configs

    ensure_credit_cost_configs()


_ensure_credit_cost_configs()


def _ensure_plan_quotas() -> None:
    from app.migrations.ensure_plan_quotas import ensure_plan_quotas

    ensure_plan_quotas()


_ensure_plan_quotas()


def _ensure_saas_hybrid_pricing() -> None:
    from app.migrations.ensure_saas_hybrid_pricing import ensure_saas_hybrid_pricing

    ensure_saas_hybrid_pricing()


_ensure_saas_hybrid_pricing()


def _ensure_chatbot_workflow_credit_logs() -> None:
    from app.migrations.ensure_chatbot_workflow_credit_logs import ensure_chatbot_workflow_credit_logs

    ensure_chatbot_workflow_credit_logs()


_ensure_chatbot_workflow_credit_logs()


def _ensure_chatbot_cskh_tables() -> None:
    from app.migrations.ensure_chatbot_cskh_tables import ensure_chatbot_cskh_tables

    ensure_chatbot_cskh_tables()


_ensure_chatbot_cskh_tables()


def _ensure_chatbot_cskh_widget_columns() -> None:
    from app.migrations.ensure_chatbot_cskh_widget_columns import ensure_chatbot_cskh_widget_columns

    ensure_chatbot_cskh_widget_columns()


_ensure_chatbot_cskh_widget_columns()


def _ensure_chatbot_cskh_credit_columns() -> None:
    from app.migrations.ensure_chatbot_cskh_credit_columns import ensure_chatbot_cskh_credit_columns

    ensure_chatbot_cskh_credit_columns()


_ensure_chatbot_cskh_credit_columns()


def _ensure_chatbot_cskh_allowed_domains() -> None:
    from app.migrations.ensure_chatbot_cskh_allowed_domains import ensure_chatbot_cskh_allowed_domains

    ensure_chatbot_cskh_allowed_domains()


_ensure_chatbot_cskh_allowed_domains()


def _ensure_chatbot_cskh_facebook() -> None:
    from app.migrations.ensure_chatbot_cskh_facebook import ensure_chatbot_cskh_facebook

    ensure_chatbot_cskh_facebook()


_ensure_chatbot_cskh_facebook()


def _ensure_chatbot_knowledge_columns() -> None:
    from app.migrations.ensure_chatbot_knowledge_columns import ensure_chatbot_knowledge_columns

    ensure_chatbot_knowledge_columns()


_ensure_chatbot_knowledge_columns()


def _ensure_chatbot_kb_tables() -> None:
    from app.migrations.ensure_chatbot_kb_tables import ensure_chatbot_kb_tables

    ensure_chatbot_kb_tables()


_ensure_chatbot_kb_tables()


def _ensure_cau_seo_fix_credit_logs() -> None:
    from app.migrations.ensure_cau_seo_fix_credit_logs import ensure_cau_seo_fix_credit_logs

    ensure_cau_seo_fix_credit_logs()


_ensure_cau_seo_fix_credit_logs()


def _ensure_submit_project_columns() -> None:
    from app.migrations.ensure_submit_project_columns import ensure_submit_project_columns

    ensure_submit_project_columns()


_ensure_submit_project_columns()


def _ensure_keyword_cluster_project_name() -> None:
    from app.migrations.ensure_keyword_cluster_project_name import ensure_keyword_cluster_project_name

    ensure_keyword_cluster_project_name()


_ensure_keyword_cluster_project_name()


def _ensure_check_free_project_column() -> None:
    from app.migrations.ensure_check_free_project_column import ensure_check_free_project_column

    ensure_check_free_project_column()


_ensure_check_free_project_column()


def _ensure_google_map_gbp_tables() -> None:
    from app.migrations.ensure_google_map_gbp_tables import ensure_google_map_gbp_tables

    ensure_google_map_gbp_tables()


_ensure_google_map_gbp_tables()


def _ensure_gbp_profile_drafts() -> None:
    from app.migrations.ensure_gbp_profile_drafts import ensure_gbp_profile_drafts

    ensure_gbp_profile_drafts()


_ensure_gbp_profile_drafts()


def _ensure_gbp_review_reply_drafts() -> None:
    from app.migrations.ensure_gbp_review_reply_drafts import ensure_gbp_review_reply_drafts

    ensure_gbp_review_reply_drafts()


_ensure_gbp_review_reply_drafts()


def _ensure_gbp_posts() -> None:
    from app.migrations.ensure_gbp_posts import ensure_gbp_posts

    ensure_gbp_posts()


_ensure_gbp_posts()


def _ensure_gbp_media() -> None:
    from app.migrations.ensure_gbp_media import ensure_gbp_media

    ensure_gbp_media()


_ensure_gbp_media()


def _ensure_gbp_verification() -> None:
    from app.migrations.ensure_gbp_verification import ensure_gbp_verification

    ensure_gbp_verification()


_ensure_gbp_verification()


def _ensure_gbp_reports() -> None:
    from app.migrations.ensure_gbp_reports import ensure_gbp_reports

    ensure_gbp_reports()


_ensure_gbp_reports()


def _ensure_gbp_leads() -> None:
    from app.migrations.ensure_gbp_leads import ensure_gbp_leads

    ensure_gbp_leads()


_ensure_gbp_leads()


def _ensure_gbp_leads_v2() -> None:
    from app.migrations.ensure_gbp_leads_v2 import ensure_gbp_leads_v2

    ensure_gbp_leads_v2()


_ensure_gbp_leads_v2()


def _ensure_saas_economics() -> None:
    from app.migrations.ensure_saas_economics import ensure_saas_economics

    ensure_saas_economics()


_ensure_saas_economics()


def _ensure_dataforseo_usage_logs() -> None:
    from app.migrations.ensure_dataforseo_usage_logs import ensure_dataforseo_usage_logs

    ensure_dataforseo_usage_logs()


_ensure_dataforseo_usage_logs()


def _ensure_wordpress_plugin_tables() -> None:
    from app.migrations.ensure_wordpress_plugin_tables import ensure_wordpress_plugin_tables

    ensure_wordpress_plugin_tables()


_ensure_wordpress_plugin_tables()


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return _templates.TemplateResponse(request=request, name="home.html", context={})


@app.get("/pricing", response_class=HTMLResponse, tags=["pages"])
def pricing_page_route(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    """Bảng giá SaaS (đăng ký tại app để luôn có route sau khi deploy/restart)."""
    return saas_pricing_page(request, db)


@app.get("/account-billing", response_class=HTMLResponse, tags=["pages"])
def account_billing_redirect(request: Request) -> HTMLResponse:
    return _templates.TemplateResponse(request=request, name="account_billing.html", context={})


@app.get("/account-billing/payment-success", response_class=HTMLResponse, tags=["pages"])
def account_billing_payment_success(request: Request) -> HTMLResponse:
    return _templates.TemplateResponse(request=request, name="payment_success.html", context={})


@app.get("/account/billing", tags=["pages"])
def account_billing_alias() -> RedirectResponse:
    """Legacy URL — mở trang thanh toán (tab credit)."""
    return RedirectResponse(url="/account-billing?tab=plans&plans=credit", status_code=302)


@app.get("/admin/affiliate", response_class=HTMLResponse, response_model=None, tags=["pages"])
def admin_affiliate_page(request: Request, db: Session = Depends(get_db)):
    gate = _admin_page_user(request, db)
    if isinstance(gate, RedirectResponse):
        return gate
    return _templates.TemplateResponse(
        request=request,
        name="admin_affiliate.html",
        context={
            "admin_nav_active": "affiliate",
            "admin_page_lead": (
                "Quản lý affiliate, duyệt hoa hồng, rút tiền và cảnh báo bất thường."
            ),
        },
    )


@app.get("/admin/billing", response_class=HTMLResponse, response_model=None, tags=["pages"])
def admin_billing_page(request: Request, db: Session = Depends(get_db)):
    gate = _admin_page_user(request, db)
    if isinstance(gate, RedirectResponse):
        return gate
    return _templates.TemplateResponse(
        request=request,
        name="admin_billing.html",
        context={
            "admin_nav_active": "billing",
            "admin_page_lead": (
                "Quản lý đơn chuyển khoản, kích hoạt gói và giao dịch SePay."
            ),
        },
    )




@app.get("/admin/backup", response_class=HTMLResponse, response_model=None, tags=["pages"])
def admin_backup_page(request: Request, db: Session = Depends(get_db)):
    gate = _admin_page_user(request, db)
    if isinstance(gate, RedirectResponse):
        return gate
    return _templates.TemplateResponse(
        request=request,
        name="admin_backup.html",
        context={
            "admin_nav_active": "backup",
            "admin_page_lead": "Sao lưu database, uploads, source code và cấu hình hạ tầng.",
        },
    )

@app.get("/admin/integrations", response_class=HTMLResponse, response_model=None, tags=["pages"])
def admin_integrations_page(request: Request, db: Session = Depends(get_db)):
    gate = _admin_page_user(request, db)
    if isinstance(gate, RedirectResponse):
        return gate
    return _templates.TemplateResponse(
        request=request,
        name="admin_integrations.html",
        context={
            "admin_nav_active": "integrations",
            "admin_page_lead": (
                "Cấu hình API tích hợp bên thứ ba — Sinbyte submit indexing."
            ),
        },
    )


@app.get("/admin/pricing", response_class=HTMLResponse, response_model=None, tags=["pages"])
def admin_pricing_page(request: Request, db: Session = Depends(get_db)):
    gate = _admin_page_user(request, db)
    if isinstance(gate, RedirectResponse):
        return gate
    return _templates.TemplateResponse(
        request=request,
        name="admin_pricing.html",
        context={
            "admin_nav_active": "pricing",
            "admin_page_lead": (
                "Quản lý bảng giá công khai: Starter, Pro, Agency, Business."
            ),
            "admin_extra_actions": (
                '<a href="/pricing" class="ab-sys-link" target="_blank" rel="noopener">'
                "Xem /pricing ↗</a>"
            ),
        },
    )


@app.get("/admin/credit-costs", response_class=HTMLResponse, response_model=None, tags=["pages"])
def admin_credit_costs_page(request: Request, db: Session = Depends(get_db)):
    gate = _admin_page_user(request, db)
    if isinstance(gate, RedirectResponse):
        return gate
    return _templates.TemplateResponse(
        request=request,
        name="admin_credit_costs.html",
        context={
            "admin_nav_active": "credit_costs",
            "admin_page_lead": (
                "Giá credit theo module/action — một ví chung cho toàn hệ thống SEOAuto."
            ),
        },
    )


@app.get("/admin/plan-quotas", response_class=HTMLResponse, response_model=None, tags=["pages"])
def admin_plan_quotas_page(request: Request, db: Session = Depends(get_db)):
    gate = _admin_page_user(request, db)
    if isinstance(gate, RedirectResponse):
        return gate
    return _templates.TemplateResponse(
        request=request,
        name="admin_plan_quotas.html",
        context={
            "admin_nav_active": "plan_quotas",
            "admin_page_lead": (
                "Quota tháng theo gói Basic, Pro, Agency, Business — song song với credit wallet."
            ),
        },
    )


@app.get("/admin/saas-economics", response_class=HTMLResponse, response_model=None, tags=["pages"])
def admin_saas_economics_page(request: Request, db: Session = Depends(get_db)):
    gate = _admin_page_user(request, db)
    if isinstance(gate, RedirectResponse):
        return gate
    return _templates.TemplateResponse(
        request=request,
        name="admin_saas_economics.html",
        context={
            "admin_nav_active": "saas_economics",
            "admin_page_lead": (
                "Theo dõi credit burn, ước tính chi phí API, doanh thu và lợi nhuận SaaS."
            ),
        },
    )


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}
