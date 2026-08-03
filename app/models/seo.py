from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_user_created_at", "user_id", "created_at"),
        Index("ix_projects_user_domain", "user_id", "domain"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    scans: Mapped[list["Scan"]] = relationship("Scan", back_populates="project", cascade="all, delete-orphan")
    knowledge_bases: Mapped[list["KnowledgeBase"]] = relationship(
        "KnowledgeBase",
        back_populates="project",
        foreign_keys="KnowledgeBase.project_id",
        cascade="all, delete-orphan",
    )


class Scan(Base):
    __tablename__ = "scans"
    __table_args__ = (
        Index("ix_scans_project_created_at", "project_id", "created_at"),
        Index("ix_scans_project_score", "project_id", "seo_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    seo_score: Mapped[int] = mapped_column(Integer, nullable=False)
    total_pages: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    project: Mapped["Project"] = relationship("Project", back_populates="scans")
    pages: Mapped[list["Page"]] = relationship("Page", back_populates="scan", cascade="all, delete-orphan")


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (
        Index("ix_pages_scan_score", "scan_id", "page_score"),
        Index("ix_pages_scan_status", "scan_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id"), index=True, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    page_score: Mapped[int] = mapped_column(Integer, nullable=False)

    scan: Mapped["Scan"] = relationship("Scan", back_populates="pages")
    issues: Mapped[list["ScanIssue"]] = relationship("ScanIssue", back_populates="page", cascade="all, delete-orphan")


class ScanIssue(Base):
    __tablename__ = "issues"
    __table_args__ = (
        Index("ix_issues_page_severity", "page_id", "severity"),
        Index("ix_issues_type_severity", "type", "severity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id"), index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(120), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    page: Mapped["Page"] = relationship("Page", back_populates="issues")


class SeoScoreApplyLog(Base):
    """Audit log — áp dụng SEO Score fix lên WordPress."""

    __tablename__ = "seo_score_apply_logs"
    __table_args__ = (
        Index("ix_seo_score_apply_logs_user_created", "user_id", "created_at"),
        Index("ix_seo_score_apply_logs_project", "project_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True, nullable=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    page_field: Mapped[str] = mapped_column(String(64), nullable=False)
    before_json: Mapped[str] = mapped_column(Text, nullable=False, default="")
    after_json: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
