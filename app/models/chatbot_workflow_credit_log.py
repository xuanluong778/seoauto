from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ChatbotWorkflowCreditLog(Base):
    """Lịch sử trừ credit cho workflow Chatbot AI."""

    __tablename__ = "chatbot_workflow_credit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    workflow: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    credit_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    error_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
