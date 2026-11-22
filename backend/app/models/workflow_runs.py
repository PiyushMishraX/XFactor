"""Persisted workflow run history for the control-tower dashboard (Step 8).

Each LangGraph thread is stored once and updated after every invocation, so the
dashboard can list what the agents actually did without re-reading every
checkpoint. The full JSON-safe workflow state is stored alongside the queryable
summary columns; the checkpoint remains the source of truth for resuming a run.

The history is **derived from real executions only**: a row is written by the
orchestration API after a run, and updated after an authenticated approval
decision. Nothing in this table is fabricated sample activity.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowRunRow(Base):
    """Summary plus recorded state for one supervisor workflow thread."""

    __tablename__ = "workflow_runs"

    thread_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(120), nullable=False, default="", index=True)
    disruption_type: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    location: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    origin: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    destination: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(48), nullable=False, default="", index=True)
    awaiting_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    risk_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    recommended_scenario_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    headline: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    execution_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
