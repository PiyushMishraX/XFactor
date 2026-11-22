"""Real tool-call recording for agent executions (Step 5).

The supervisor must be able to show *which* tools actually ran, not a plausible
narrative. This module provides a context-local recorder that the LangGraph agent
nodes activate around each execution:

* :class:`ToolCallRecorder` collects :class:`ToolInvocation` rows.
* :func:`call_recorded` wraps one callable (a deterministic engine or the Gemini
  service) and records its duration, outcome and whether it failed.
* :class:`RecordingConnector` is a transparent proxy that records every method
  call on an external connector — the call still goes to the real adapter, only
  the observation is added.
* :func:`record_tool_call` lets a piece of code add an explicit row.

Recorder functions are **no-ops when no recorder is active**, so calling an
agent directly in a unit test behaves exactly as before. Arguments and outcomes
are stored as short JSON-safe summaries; credentials are never passed to the
recorder.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from time import perf_counter
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence

from pydantic import BaseModel

from app.integrations.base import IntegrationNotConfiguredError
from app.schemas.collaboration_schemas import ToolCallStatus, ToolInvocation

logger = logging.getLogger(__name__)

_MAX_TEXT = 200

_ACTIVE_RECORDER: ContextVar[Optional["ToolCallRecorder"]] = ContextVar(
    "xfactor_tool_recorder", default=None
)


class ToolCallRecorder:
    """Collects the tool invocations of one agent execution."""

    def __init__(self) -> None:
        self._calls: List[ToolInvocation] = []

    @property
    def calls(self) -> List[ToolInvocation]:
        """A copy of the recorded invocations, in execution order."""
        return list(self._calls)

    def record(self, invocation: ToolInvocation) -> ToolInvocation:
        self._calls.append(invocation)
        return invocation

    @contextmanager
    def activate(self) -> Iterator["ToolCallRecorder"]:
        """Make this recorder the active one for the current context."""
        token = _ACTIVE_RECORDER.set(self)
        try:
            yield self
        finally:
            _ACTIVE_RECORDER.reset(token)


def active_recorder() -> Optional[ToolCallRecorder]:
    """The recorder active in this context, or ``None`` outside an agent node."""
    return _ACTIVE_RECORDER.get()


def record_tool_call(
    tool: str,
    arguments: Optional[Dict[str, Any]] = None,
    outcome: str = "",
    *,
    status: ToolCallStatus | str = ToolCallStatus.OK,
    duration_ms: float = 0.0,
    is_mock: bool = False,
) -> Optional[ToolInvocation]:
    """Record one invocation explicitly. No-op when no recorder is active."""
    recorder = _ACTIVE_RECORDER.get()
    if recorder is None:
        return None
    invocation = ToolInvocation(
        tool=tool,
        arguments=_safe_arguments(arguments or {}),
        outcome=_truncate(outcome),
        status=ToolCallStatus(status),
        duration_ms=round(max(0.0, duration_ms), 3),
        is_mock=is_mock,
    )
    return recorder.record(invocation)


def call_recorded(
    tool: str,
    arguments: Optional[Dict[str, Any]],
    fn: Callable[..., Any],
    /,
    *args: Any,
    summarise: Optional[Callable[[Any], str]] = None,
    is_mock: bool = False,
    **kwargs: Any,
) -> Any:
    """Call ``fn`` and record the invocation, re-raising any failure.

    The call is always made; recording is best-effort and never changes the
    result or the exception.
    """
    started = perf_counter()
    try:
        result = fn(*args, **kwargs)
    except IntegrationNotConfiguredError as exc:
        _record_failure(tool, arguments, exc, started, ToolCallStatus.UNAVAILABLE, is_mock)
        raise
    except Exception as exc:  # noqa: BLE001 - the failure is recorded and re-raised
        _record_failure(tool, arguments, exc, started, ToolCallStatus.ERROR, is_mock)
        raise

    outcome = summarise(result) if summarise is not None else summarise_result(result)
    record_tool_call(
        tool,
        arguments,
        outcome,
        duration_ms=(perf_counter() - started) * 1000.0,
        is_mock=is_mock or bool(result_is_mock(result)),
    )
    return result


class RecordingConnector:
    """Transparent proxy that records every connector method call.

    Attribute access and return values are unchanged; only calls are observed.
    """

    def __init__(self, name: str, target: Any) -> None:
        object.__setattr__(self, "_recording_name", name)
        object.__setattr__(self, "_recording_target", target)

    @property
    def name(self) -> str:
        return str(getattr(self._recording_target, "name", self._recording_name))

    @property
    def is_mock(self) -> bool:
        return bool(getattr(self._recording_target, "is_mock", False))

    def __getattr__(self, attribute: str) -> Any:
        target = object.__getattribute__(self, "_recording_target")
        value = getattr(target, attribute)
        if not callable(value):
            return value

        name = object.__getattribute__(self, "_recording_name")
        is_mock = bool(getattr(target, "is_mock", False))

        @wraps(value)
        def recorded(*args: Any, **kwargs: Any) -> Any:
            tool = f"{name}.{attribute}"
            arguments = _call_arguments(args, kwargs)
            started = perf_counter()
            try:
                result = value(*args, **kwargs)
            except IntegrationNotConfiguredError as exc:
                _record_failure(tool, arguments, exc, started, ToolCallStatus.UNAVAILABLE, is_mock)
                raise
            except Exception as exc:  # noqa: BLE001 - recorded and re-raised
                _record_failure(tool, arguments, exc, started, ToolCallStatus.ERROR, is_mock)
                raise
            record_tool_call(
                tool,
                arguments,
                summarise_result(result),
                duration_ms=(perf_counter() - started) * 1000.0,
                is_mock=is_mock or bool(result_is_mock(result)),
            )
            return result

        return recorded


def wrap_connector(name: str, target: Any) -> Any:
    """Wrap ``target`` so its calls are recorded; leave an existing proxy alone."""
    if isinstance(target, RecordingConnector):
        return target
    return RecordingConnector(name, target)


def summarise_result(value: Any) -> str:
    """A short, JSON-safe description of a tool result."""
    if value is None:
        return "no result"
    if isinstance(value, str):
        return _truncate(value)
    if isinstance(value, (list, tuple, set)):
        return f"{len(value)} item(s)"
    if isinstance(value, dict):
        return f"{len(value)} key(s)"
    if isinstance(value, BaseModel):
        return value.__class__.__name__
    return _truncate(type(value).__name__)


def result_is_mock(value: Any) -> Optional[bool]:
    """Whether a tool result carries labelled simulated data, when detectable."""
    provenance = getattr(value, "provenance", None)
    if provenance is not None and hasattr(provenance, "is_mock"):
        return bool(provenance.is_mock)
    if isinstance(value, (list, tuple)) and value:
        return result_is_mock(value[0])
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record_failure(
    tool: str,
    arguments: Optional[Dict[str, Any]],
    exc: Exception,
    started: float,
    status: ToolCallStatus,
    is_mock: bool,
) -> None:
    logger.warning("Tool %s failed (%s): %s", tool, status.value, exc)
    record_tool_call(
        tool,
        arguments,
        f"{type(exc).__name__}: {exc}",
        status=status,
        duration_ms=(perf_counter() - started) * 1000.0,
        is_mock=is_mock,
    )


def _call_arguments(args: Sequence[Any], kwargs: Dict[str, Any]) -> Dict[str, Any]:
    arguments: Dict[str, Any] = {}
    if args:
        arguments["args"] = [_safe_value(value) for value in args]
    for key, value in kwargs.items():
        arguments[key] = _safe_value(value)
    return arguments


def _safe_arguments(arguments: Dict[str, Any]) -> Dict[str, Any]:
    return {str(key): _safe_value(value) for key, value in arguments.items()}


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _truncate(value)
    if isinstance(value, (list, tuple, set)):
        return [_safe_value(item) for item in list(value)[:10]]
    if isinstance(value, dict):
        return {str(key): _safe_value(item) for key, item in list(value.items())[:10]}
    if isinstance(value, BaseModel):
        return value.__class__.__name__
    return _truncate(str(value))


def _truncate(text: str, limit: int = _MAX_TEXT) -> str:
    cleaned = " ".join(str(text).split())
    return cleaned if len(cleaned) <= limit else f"{cleaned[:limit]}..."


__all__ = [
    "RecordingConnector",
    "ToolCallRecorder",
    "active_recorder",
    "call_recorded",
    "record_tool_call",
    "result_is_mock",
    "summarise_result",
    "wrap_connector",
]
