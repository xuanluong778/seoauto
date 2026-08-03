"""Google Business Profile — OAuth connections & locations (Google Map SEO)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class GbpOAuthConnection(Base):
    __tablename__ = "gbp_oauth_connections"
    __table_args__ = (
        Index("ix_gbp_conn_user_status", "user_id", "status"),
        UniqueConstraint("user_id", "google_account_resource", name="uq_gbp_conn_user_account"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    google_account_resource: Mapped[str] = mapped_column(String(128), nullable=False)
    google_account_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    google_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'active'"))
    last_sync_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class GbpLocation(Base):
    __tablename__ = "gbp_locations"
    __table_args__ = (
        Index("ix_gbp_loc_user", "user_id"),
        UniqueConstraint("connection_id", "google_location_resource", name="uq_gbp_loc_conn_resource"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("gbp_oauth_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    google_location_resource: Mapped[str] = mapped_column(String(160), nullable=False)
    google_account_resource: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line: Mapped[str | None] = mapped_column(String(500), nullable=True)
    locality: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    website_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    primary_category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verification_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    audit_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class GbpProfileDraft(Base):
    """Nháp nội dung tối ưu hồ sơ GBP (AI)."""

    __tablename__ = "gbp_profile_drafts"
    __table_args__ = (
        Index("ix_gbp_draft_user_loc", "user_id", "location_key"),
        UniqueConstraint("user_id", "location_key", "content_type", name="uq_gbp_draft_user_loc_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    location_key: Mapped[str] = mapped_column(String(64), nullable=False)
    gbp_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("gbp_locations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    content_type: Mapped[str] = mapped_column(String(48), nullable=False)
    input_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class GbpReviewReplyDraft(Base):
    """Nháp phản hồi review GBP."""

    __tablename__ = "gbp_review_reply_drafts"
    __table_args__ = (
        Index("ix_gbp_rev_draft_user_loc", "user_id", "location_key"),
        UniqueConstraint("user_id", "location_key", "review_id", name="uq_gbp_rev_draft_user_loc_review"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    location_key: Mapped[str] = mapped_column(String(64), nullable=False)
    review_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reply_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class GbpPost(Base):
    """Bài đăng Google Map — nháp / lịch / đã đăng."""

    __tablename__ = "gbp_posts"
    __table_args__ = (
        Index("ix_gbp_post_user_loc", "user_id", "location_key"),
        Index("ix_gbp_post_status_sched", "status", "scheduled_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    location_key: Mapped[str] = mapped_column(String(64), nullable=False)
    gbp_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("gbp_locations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    post_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'draft'"))
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    cta_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cta_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    image_suggestions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    schedule_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    google_post_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class GbpMedia(Base):
    """Ảnh & media Google Map — lưu nội bộ / đăng GBP."""

    __tablename__ = "gbp_media"
    __table_args__ = (
        Index("ix_gbp_media_user_loc", "user_id", "location_key"),
        Index("ix_gbp_media_type", "media_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    location_key: Mapped[str] = mapped_column(String(64), nullable=False)
    gbp_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("gbp_locations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    media_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'local'"))
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    public_url: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width_px: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height_px: Mapped[int | None] = mapped_column(Integer, nullable=True)
    suggested_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    google_media_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class GbpMediaReminder(Base):
    """Nhắc thêm ảnh mới hàng tuần."""

    __tablename__ = "gbp_media_reminders"
    __table_args__ = (
        UniqueConstraint("user_id", "location_key", name="uq_gbp_media_rem_user_loc"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    location_key: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    remind_weekday: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    last_reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class GbpVerificationKit(Base):
    """Trợ lý xác minh Google Map — checklist, ghi chú."""

    __tablename__ = "gbp_verification_kits"
    __table_args__ = (
        UniqueConstraint("user_id", "location_key", name="uq_gbp_verif_kit_user_loc"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    location_key: Mapped[str] = mapped_column(String(64), nullable=False)
    gbp_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("gbp_locations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    manual_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    checklist_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class GbpVerificationAsset(Base):
    """Ảnh / tài liệu phục vụ xác minh Map."""

    __tablename__ = "gbp_verification_assets"
    __table_args__ = (
        Index("ix_gbp_verif_asset_user_loc", "user_id", "location_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    location_key: Mapped[str] = mapped_column(String(64), nullable=False)
    kit_id: Mapped[int | None] = mapped_column(
        ForeignKey("gbp_verification_kits.id", ondelete="CASCADE"), nullable=True, index=True
    )
    asset_type: Mapped[str] = mapped_column(String(24), nullable=False, server_default=text("'photo'"))
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    public_url: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GbpReportSnapshot(Base):
    """Snapshot chỉ số báo cáo Google Map theo thời gian."""

    __tablename__ = "gbp_report_snapshots"
    __table_args__ = (
        Index("ix_gbp_report_user_loc_date", "user_id", "location_key", "snapshot_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    location_key: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'month'"))
    source: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'demo'"))
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GbpReportBranding(Base):
    """Cấu trúc white-label báo cáo (agency) — sẵn sàng mở rộng."""

    __tablename__ = "gbp_report_branding"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_gbp_report_branding_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agency_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    accent_color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    footer_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class GbpLeadScan(Base):
    """Lịch sử quét lead Google Map theo user."""

    __tablename__ = "gbp_lead_scans"
    __table_args__ = (
        Index("ix_gbp_lead_scan_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'keyword'"))
    keyword: Mapped[str | None] = mapped_column(String(300), nullable=True)
    category: Mapped[str | None] = mapped_column(String(200), nullable=True)
    province: Mapped[str | None] = mapped_column(String(120), nullable=True)
    district: Mapped[str | None] = mapped_column(String(120), nullable=True)
    radius_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_limit: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("20"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'completed'"))
    credits_charged: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    unique_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    params_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    cache_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    data_source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'api'"))
    api_request_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    search_request_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    detail_request_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    geocode_request_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cached_from_scan_id: Mapped[int | None] = mapped_column(
        ForeignKey("gbp_lead_scans.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GbpLead(Base):
    """Lead doanh nghiệp từ Google Places."""

    __tablename__ = "gbp_leads"
    __table_args__ = (
        Index("ix_gbp_lead_scan", "scan_id"),
        Index("ix_gbp_lead_user_place", "user_id", "place_id"),
        UniqueConstraint("scan_id", "place_id", name="uq_gbp_lead_scan_place"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_id: Mapped[int] = mapped_column(
        ForeignKey("gbp_lead_scans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    place_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    rating: Mapped[float | None] = mapped_column(nullable=True)
    review_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    latitude: Mapped[float | None] = mapped_column(nullable=True)
    longitude: Mapped[float | None] = mapped_column(nullable=True)
    maps_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    lead_status: Mapped[str] = mapped_column(String(24), nullable=False, server_default=text("'new'"))
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    detail_fetched: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    data_source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'search'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GbpLeadApiLog(Base):
    """Log lỗi / quota Google Places (không lưu API key)."""

    __tablename__ = "gbp_lead_api_logs"
    __table_args__ = (
        Index("ix_gbp_lead_api_log_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scan_id: Mapped[int | None] = mapped_column(
        ForeignKey("gbp_lead_scans.id", ondelete="SET NULL"), nullable=True, index=True
    )
    endpoint: Mapped[str] = mapped_column(String(120), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    keyword: Mapped[str | None] = mapped_column(String(300), nullable=True)
    province: Mapped[str | None] = mapped_column(String(120), nullable=True)
    district: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
