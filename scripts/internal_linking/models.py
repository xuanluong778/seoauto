from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class InternalLinkArticle(Base):
    """
    Canonical local representation of a WordPress post/page.
    """

    __tablename__ = "il_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # WordPress identifiers
    wp_site: Mapped[str] = mapped_column(String(255), nullable=False)  # base URL e.g. https://example.com
    wp_id: Mapped[int] = mapped_column(Integer, nullable=False)
    wp_type: Mapped[str] = mapped_column(String(32), nullable=False)  # "post" | "page"

    url: Mapped[str] = mapped_column(String(900), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(700), nullable=False, default="")
    excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="")

    content_html: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    lang: Mapped[str] = mapped_column(String(24), nullable=False, default="und")
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )
    updated_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Convenience counters
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedded_chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    chunks: Mapped[list["InternalLinkChunk"]] = relationship(
        back_populates="article", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint("wp_site", "wp_id", "wp_type", name="uq_il_article_site_id_type"),
        Index("ix_il_articles_wp_site", "wp_site"),
        Index("ix_il_articles_url", "url"),
        Index("ix_il_articles_wp_type", "wp_type"),
    )


class InternalLinkChunk(Base):
    """
    Chunk of an article, typically derived from headings and paragraphs.
    Stores embedding as float32 bytes for fast cosine similarity.
    """

    __tablename__ = "il_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("il_articles.id", ondelete="CASCADE"), nullable=False, index=True)

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # Hierarchical context (e.g., "H1 > H2 > H3")
    heading_path: Mapped[str] = mapped_column(String(900), nullable=False, default="")
    heading_text: Mapped[str] = mapped_column(String(700), nullable=False, default="")

    # Plain text and an optional small HTML fragment for context extraction
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    html_fragment: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Character offsets in the article plain text (best-effort)
    start_char: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_char: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Embedding storage
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, default=b"")
    embedded_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    article: Mapped["InternalLinkArticle"] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("article_id", "chunk_index", name="uq_il_chunk_article_index"),
        Index("ix_il_chunks_article_heading", "article_id", "heading_path"),
    )

