"""Single-flight guard for supervisor workflow runs.

One supervisor run already fans out to five agents and several Gemini calls. Two
overlapping runs multiply that load and can exhaust the free-tier daily quota, so
the start endpoints admit at most one run at a time.

The guard is process-wide and uses a non-blocking ``threading.Lock``. FastAPI
runs these synchronous endpoints in a worker thread, so the lock is the right
primitive. The deployment runs a single uvicorn worker; a multi-worker or
multi-replica deployment would need a database advisory lock instead.
"""

from __future__ import annotations

import threading
from typing import Optional


class WorkflowBusyError(RuntimeError):
    """Raised when a supervisor run is already in flight in this process."""

    def __init__(self, active_thread_id: str) -> None:
        super().__init__(
            f"A supervisor workflow is already running for thread {active_thread_id!r}."
        )
        self.active_thread_id = active_thread_id


class WorkflowGuard:
    """Admit one workflow run at a time and remember which thread is running."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_thread_id: Optional[str] = None

    @property
    def active_thread_id(self) -> Optional[str]:
        """The thread of the run in flight, or ``None`` when idle."""
        return self._active_thread_id

    def try_begin(self, thread_id: str) -> None:
        """Claim the single slot for ``thread_id``.

        Raises:
            WorkflowBusyError: Another run already holds the slot.
        """
        if not self._lock.acquire(blocking=False):
            raise WorkflowBusyError(self._active_thread_id or "another run")
        self._active_thread_id = thread_id

    def end(self) -> None:
        """Release the slot. Safe to call only after a successful claim."""
        self._active_thread_id = None
        self._lock.release()


__all__ = ["WorkflowBusyError", "WorkflowGuard"]
