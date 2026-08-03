from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    has_password: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    credit_balance: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    chatbot_cskh_bonus_credits: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'user'"), default="user")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"), default="active")
    api_access_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    use_admin_api_pool: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    allow_custom_api_key: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    free_usage_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    trial_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    trial_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    trial_used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    trial_credit_used: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    projects: Mapped[list["Project"]] = relationship("Project", backref="user", cascade="all, delete-orphan")
    knowledge_bases: Mapped[list["KnowledgeBase"]] = relationship(
        "KnowledgeBase",
        back_populates="user",
        foreign_keys="KnowledgeBase.user_id",
        cascade="all, delete-orphan",
    )
