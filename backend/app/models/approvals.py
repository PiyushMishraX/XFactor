"""ORM models for the human approval queue (Step 6).

One row per workflow thread holds the *current* proposal awaiting a decision plus
the complete decision history and any execution report. The proposal and history
payloads are stored as JSON text so the row survives Pydantic schema evolution
without a migration for every field, while the columns that are queried —
thread, version, status and approval level — stay first-class.

``thread_id`` is the primary key because a workflow thread is a single approval
object: when a reviewer asks for modifications, the thread receives a new
proposal version and the row is updated in place, preserving its history.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ApprovalRequestRow(Base):
    """The persisted approval queue item for one workflow thread."""

    __tablename__ = "approval_requests"

    thread_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    proposal_id: Mapped[str] = mapped_column(String(160), nullable=False)
    proposal_version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    approval_level: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    proposal_json: Mapped[str] = mapped_column(Text, nullable=False)
    decision_history_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    execution_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
