"""
Knowledge Base — SQL persistence (global / user / project scopes).

JSON store at data/ai_knowledge_bases.json remains unchanged; these tables are additive.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.seo import Project
    from app.models.user import User

# --- Scope & status constants (app-level; stored as VARCHAR) ---

SCOPE_GLOBAL = "global"
SCOPE_USER = "user"
SCOPE_PROJECT = "project"
SCOPES = (SCOPE_GLOBAL, SCOPE_USER, SCOPE_PROJECT)

KB_STATUS_ACTIVE = "active"
KB_STATUS_DRAFT = "draft"
KB_STATUS_ARCHIVED = "archived"
KB_STATUSES = (KB_STATUS_ACTIVE, KB_STATUS_DRAFT, KB_STATUS_ARCHIVED)

ITEM_STATUS_ACTIVE = "active"
ITEM_STATUS_DRAFT = "draft"
ITEM_STATUS_ARCHIVED = "archived"

VERSION_ENTITY_BASE = "knowledge_base"
VERSION_ENTITY_CATEGORY = "knowledge_category"
VERSION_ENTITY_ITEM = "knowledge_item"


class KnowledgeBase(Base):
    """
    Root container for brand/context knowledge.

    scope_type:
      - global: user_id and project_id NULL (admin-managed defaults)
      - user: user_id set, project_id NULL
      - project: user_id and project_id set (SEO project / website)
    """

    __tablename__ = "knowledge_bases"
    __table_args__ = (
        CheckConstraint(
            "(scope_type = 'global' AND user_id IS NULL AND project_id IS NULL) OR "
            "(scope_type = 'user' AND user_id IS NOT NULL AND project_id IS NULL) OR "
            "(scope_type = 'project' AND user_id IS NOT NULL AND project_id IS NOT NULL)",
            name="ck_knowledge_bases_scope",
        ),
        Index("ix_knowledge_bases_scope_type", "scope_type"),
        Index("ix_knowledge_bases_status", "status"),
        Index("ix_knowledge_bases_user_status", "user_id", "status"),
        Index("ix_knowledge_bases_project_status", "project_id", "status"),
        Index("ix_knowledge_bases_scope_user", "scope_type", "user_id"),
        Index("ix_knowledge_bases_scope_project", "scope_type", "project_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False, default=SCOPE_USER)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    brand_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    tone: Mapped[str | None] = mapped_column(String(32), nullable=True, server_default=text("'professional'"))
    language: Mapped[str | None] = mapped_column(String(16), nullable=True, server_default=text("'vi'"))

    products_services: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_facts: Mapped[str | None] = mapped_column(Text, nullable=True)
    avoid_topics: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'active'"))
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[User | None] = relationship("User", back_populates="knowledge_bases")
    project: Mapped[Project | None] = relationship("Project", back_populates="knowledge_bases")
    categories: Mapped[list["KnowledgeCategory"]] = relationship(
        "KnowledgeCategory", back_populates="knowledge_base", cascade="all, delete-orphan"
    )
    items: Mapped[list["KnowledgeItem"]] = relationship(
        "KnowledgeItem", back_populates="knowledge_base", cascade="all, delete-orphan"
    )


class KnowledgeCategory(Base):
    """Hierarchical grouping inside a knowledge base."""

    __tablename__ = "knowledge_categories"
    __table_args__ = (
        Index("ix_knowledge_categories_status", "status"),
        Index("ix_knowledge_categories_base_status", "knowledge_base_id", "status"),
        UniqueConstraint("knowledge_base_id", "slug", name="uq_knowledge_categories_base_slug"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    knowledge_base_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_categories.id", ondelete="SET NULL"), nullable=True, index=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'active'"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    knowledge_base: Mapped["KnowledgeBase"] = relationship("KnowledgeBase", back_populates="categories")
    parent: Mapped["KnowledgeCategory | None"] = relationship(
        "KnowledgeCategory", remote_side="KnowledgeCategory.id", back_populates="children"
    )
    children: Mapped[list["KnowledgeCategory"]] = relationship("KnowledgeCategory", back_populates="parent")
    items: Mapped[list["KnowledgeItem"]] = relationship("KnowledgeItem", back_populates="category")


class KnowledgeItem(Base):
    """Atomic knowledge unit (FAQ, policy, product note, document excerpt, …)."""

    __tablename__ = "knowledge_items"
    __table_args__ = (
        Index("ix_knowledge_items_status", "status"),
        Index("ix_knowledge_items_item_type", "item_type"),
        Index("ix_knowledge_items_base_status", "knowledge_base_id", "status"),
        Index("ix_knowledge_items_base_type", "knowledge_base_id", "item_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    knowledge_base_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_categories.id", ondelete="SET NULL"), nullable=True, index=True
    )

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    content_format: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'markdown'"))
    item_type: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'snippet'"))

    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'active'"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    knowledge_base: Mapped["KnowledgeBase"] = relationship("KnowledgeBase", back_populates="items")
    category: Mapped["KnowledgeCategory | None"] = relationship("KnowledgeCategory", back_populates="items")
    embeddings: Mapped[list["KnowledgeEmbedding"]] = relationship(
        "KnowledgeEmbedding", back_populates="knowledge_item", cascade="all, delete-orphan"
    )


class KnowledgeEmbedding(Base):
    """
    Vector-ready chunks for RAG (embedding stored as JSON text for SQLite/Postgres portability).
    Replace with pgvector column in a later migration when needed.
    """

    __tablename__ = "knowledge_embeddings"
    __table_args__ = (
        Index("ix_knowledge_embeddings_model", "embedding_model"),
        UniqueConstraint("knowledge_item_id", "chunk_index", "embedding_model", name="uq_knowledge_embeddings_chunk"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    knowledge_item_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_items.id", ondelete="CASCADE"), nullable=False, index=True
    )

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)

    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    knowledge_item: Mapped["KnowledgeItem"] = relationship("KnowledgeItem", back_populates="embeddings")


class KnowledgeVersion(Base):
    """Immutable snapshot when a base/category/item is updated."""

    __tablename__ = "knowledge_versions"
    __table_args__ = (
        Index("ix_knowledge_versions_entity", "entity_type", "entity_id"),
        Index("ix_knowledge_versions_user_id", "changed_by_user_id"),
        Index("ix_knowledge_versions_created_at", "created_at"),
        UniqueConstraint("entity_type", "entity_id", "version_number", name="uq_knowledge_versions_entity_ver"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)

    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)

    changed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    change_note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
