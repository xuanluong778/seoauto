"""Chatbot CSKH — database models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class ChatbotBot(Base):
    __tablename__ = "chatbot_bots"
    __table_args__ = (
        Index("ix_chatbot_bots_user_created", "user_id", "created_at"),
        Index("ix_chatbot_bots_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    website_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    allowed_domains: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    bot_name: Mapped[str] = mapped_column(String(120), nullable=False)
    business_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    hotline: Mapped[str | None] = mapped_column(String(64), nullable=True)
    main_services: Mapped[str | None] = mapped_column(Text, nullable=True)
    consultation_tone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    greeting: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'draft'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    knowledge_sources: Mapped[list["ChatbotKnowledgeSource"]] = relationship(
        "ChatbotKnowledgeSource", back_populates="bot", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["ChatbotConversation"]] = relationship(
        "ChatbotConversation", back_populates="bot", cascade="all, delete-orphan"
    )
    leads: Mapped[list["ChatbotLead"]] = relationship(
        "ChatbotLead", back_populates="bot", cascade="all, delete-orphan"
    )
    usage_rows: Mapped[list["ChatbotUsage"]] = relationship(
        "ChatbotUsage", back_populates="bot", cascade="all, delete-orphan"
    )
    facebook_pages: Mapped[list["ChatbotFacebookPage"]] = relationship(
        "ChatbotFacebookPage", back_populates="bot", cascade="all, delete-orphan"
    )


class ChatbotKnowledgeSource(Base):
    __tablename__ = "chatbot_knowledge_sources"
    __table_args__ = (Index("ix_chatbot_ks_bot", "bot_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[int] = mapped_column(
        ForeignKey("chatbot_bots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'pending'"))
    crawl_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    bot: Mapped[ChatbotBot] = relationship("ChatbotBot", back_populates="knowledge_sources")


class ChatbotConversation(Base):
    __tablename__ = "chatbot_conversations"
    __table_args__ = (
        Index("ix_chatbot_conv_user_created", "user_id", "created_at"),
        Index("ix_chatbot_conv_bot", "bot_id"),
        Index("ix_chatbot_conv_session", "session_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[int] = mapped_column(
        ForeignKey("chatbot_bots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'website'"))
    external_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    channel_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_user_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    visitor_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    visitor_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'open'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    bot: Mapped[ChatbotBot] = relationship("ChatbotBot", back_populates="conversations")
    messages: Mapped[list["ChatbotMessage"]] = relationship(
        "ChatbotMessage", back_populates="conversation", cascade="all, delete-orphan"
    )
    leads: Mapped[list["ChatbotLead"]] = relationship(
        "ChatbotLead", back_populates="conversation", cascade="all, delete-orphan"
    )


class ChatbotMessage(Base):
    __tablename__ = "chatbot_messages"
    __table_args__ = (Index("ix_chatbot_msg_conv_created", "conversation_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("chatbot_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[ChatbotConversation] = relationship("ChatbotConversation", back_populates="messages")


class ChatbotLead(Base):
    __tablename__ = "chatbot_leads"
    __table_args__ = (
        Index("ix_chatbot_leads_bot", "bot_id"),
        Index("ix_chatbot_leads_user", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[int] = mapped_column(
        ForeignKey("chatbot_bots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("chatbot_conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    need: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'new'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    bot: Mapped[ChatbotBot] = relationship("ChatbotBot", back_populates="leads")
    conversation: Mapped[ChatbotConversation | None] = relationship(
        "ChatbotConversation", back_populates="leads"
    )


class ChatbotUsage(Base):
    __tablename__ = "chatbot_usage"
    __table_args__ = (
        UniqueConstraint("user_id", "bot_id", "month", name="uq_chatbot_usage_user_bot_month"),
        Index("ix_chatbot_usage_user_month", "user_id", "month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bot_id: Mapped[int | None] = mapped_column(
        ForeignKey("chatbot_bots.id", ondelete="SET NULL"), nullable=True, index=True
    )
    month: Mapped[str] = mapped_column(String(7), nullable=False)
    ai_replies: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    credits_used: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    bot: Mapped[ChatbotBot | None] = relationship("ChatbotBot", back_populates="usage_rows")


class ChatbotFacebookPage(Base):
    __tablename__ = "chatbot_facebook_pages"
    __table_args__ = (
        UniqueConstraint("page_id", name="uq_chatbot_fb_page_id"),
        Index("ix_chatbot_fb_user_bot", "user_id", "bot_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bot_id: Mapped[int] = mapped_column(
        ForeignKey("chatbot_bots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_id: Mapped[str] = mapped_column(String(64), nullable=False)
    page_name: Mapped[str] = mapped_column(String(200), nullable=False)
    page_access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'connected'"))
    webhook_subscribed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    bot: Mapped[ChatbotBot] = relationship("ChatbotBot", back_populates="facebook_pages")
