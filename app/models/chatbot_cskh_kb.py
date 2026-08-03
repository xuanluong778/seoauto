"""Chatbot CSKH — knowledge map / graph (per bot)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class ChatbotKbMap(Base):
    __tablename__ = "chatbot_kb_maps"
    __table_args__ = (
        Index("ix_chatbot_kb_maps_user_bot", "user_id", "bot_id"),
        Index("ix_chatbot_kb_maps_bot_status", "bot_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bot_id: Mapped[int] = mapped_column(
        ForeignKey("chatbot_bots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False, server_default=text("'Sơ đồ tri thức'"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'draft'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    nodes: Mapped[list["ChatbotKbNode"]] = relationship(
        "ChatbotKbNode", back_populates="map", cascade="all, delete-orphan"
    )
    edges: Mapped[list["ChatbotKbEdge"]] = relationship(
        "ChatbotKbEdge", back_populates="map", cascade="all, delete-orphan"
    )


class ChatbotKbNode(Base):
    __tablename__ = "chatbot_kb_nodes"
    __table_args__ = (
        Index("ix_chatbot_kb_nodes_map", "map_id"),
        Index("ix_chatbot_kb_nodes_map_active", "map_id", "is_active"),
        Index("ix_chatbot_kb_nodes_parent", "parent_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    map_id: Mapped[int] = mapped_column(
        ForeignKey("chatbot_kb_maps.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("chatbot_kb_nodes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    node_type: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'node'"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[str | None] = mapped_column(String(500), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    map: Mapped["ChatbotKbMap"] = relationship("ChatbotKbMap", back_populates="nodes")
    parent: Mapped["ChatbotKbNode | None"] = relationship(
        "ChatbotKbNode", remote_side="ChatbotKbNode.id", back_populates="children"
    )
    children: Mapped[list["ChatbotKbNode"]] = relationship("ChatbotKbNode", back_populates="parent")


class ChatbotKbEdge(Base):
    __tablename__ = "chatbot_kb_edges"
    __table_args__ = (Index("ix_chatbot_kb_edges_map", "map_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    map_id: Mapped[int] = mapped_column(
        ForeignKey("chatbot_kb_maps.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_node_id: Mapped[int] = mapped_column(
        ForeignKey("chatbot_kb_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_node_id: Mapped[int] = mapped_column(
        ForeignKey("chatbot_kb_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'child'"))

    map: Mapped["ChatbotKbMap"] = relationship("ChatbotKbMap", back_populates="edges")
