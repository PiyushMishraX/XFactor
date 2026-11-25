"""Deterministic Gemini key assignment per agent.

Multiple API keys can be configured so the five agents do not all compete for one
free-tier bucket. Assignment is deterministic: agents are taken in roadmap order
and receive keys round-robin, unless ``GEMINI_KEY_SLOTS`` overrides a slot.

Key material is never logged; only slot indexes appear in messages.
"""

from __future__ import annotations

import logging
from typing import Dict, Mapping, Tuple

from app.config.settings import Settings

logger = logging.getLogger(__name__)

#: Stable assignment order — also the order used for round-robin slots.
AGENT_ORDER: tuple[str, ...] = (
    "disruption_sensing",
    "scenario_planning",
    "rerouting_logistics",
    "inventory_rebalancing",
    "compliance_audit",
)


def parse_key_slots(raw: str) -> Dict[str, int]:
    """Parse ``agent=index`` pairs from ``GEMINI_KEY_SLOTS``.

    Raises:
        ValueError: An entry is malformed, names an unknown agent or uses a
            negative slot.
    """
    slots: Dict[str, int] = {}
    for chunk in raw.split(","):
        entry = chunk.strip()
        if not entry:
            continue
        agent, separator, index_text = entry.partition("=")
        agent = agent.strip()
        if not separator or not agent:
            raise ValueError(
                f"Invalid GEMINI_KEY_SLOTS entry {entry!r}; expected 'agent=index'."
            )
        if agent not in AGENT_ORDER:
            raise ValueError(
                f"GEMINI_KEY_SLOTS names unknown agent {agent!r}; "
                f"expected one of {', '.join(AGENT_ORDER)}."
            )
        try:
            slot = int(index_text.strip())
        except ValueError as exc:
            raise ValueError(
                f"Invalid GEMINI_KEY_SLOTS slot {index_text!r} for {agent!r}; "
                "expected a zero-based integer."
            ) from exc
        if slot < 0:
            raise ValueError(
                f"Invalid GEMINI_KEY_SLOTS slot {slot} for {agent!r}; must be >= 0."
            )
        slots[agent] = slot
    return slots


def _agent_slots(settings: Settings) -> Dict[str, int]:
    """Resolve each agent's zero-based key slot, applying overrides.

    Raises:
        ValueError: A slot override points past the configured key list.
    """
    keys = settings.gemini_api_keys
    overrides = parse_key_slots(settings.GEMINI_KEY_SLOTS)
    slots: Dict[str, int] = {}
    for position, agent in enumerate(AGENT_ORDER):
        slot = overrides.get(agent, position % len(keys))
        if slot >= len(keys):
            raise ValueError(
                f"GEMINI_KEY_SLOTS assigns {agent!r} to slot {slot}, but only "
                f"{len(keys)} key(s) are configured."
            )
        slots[agent] = slot
    return slots


def resolve_agent_keys(settings: Settings) -> Mapping[str, str]:
    """Return ``{agent_name: api_key}`` for the configured keys.

    An empty mapping means no key is configured anywhere; callers then keep the
    existing fail-loud behaviour rather than inventing a key.

    Raises:
        ValueError: A slot override points past the configured key list.
    """
    order = resolve_agent_key_order(settings)
    if not order:
        return {}
    logger.info(
        "Gemini keys assigned across %s agent(s) using %s key slot(s).",
        len(order),
        len(settings.gemini_api_keys),
    )
    return {agent: keys[0] for agent, keys in order.items()}


def resolve_agent_key_order(settings: Settings) -> Mapping[str, Tuple[str, ...]]:
    """Return each agent's full key order, starting at its assigned slot.

    The assigned key comes first so it keeps the agent's normal share of the
    load; the remaining keys follow in rotation so a quota failure on one key
    falls through to the next instead of stopping the agent.
    """
    keys = settings.gemini_api_keys
    if not keys:
        return {}
    rotated: Dict[str, Tuple[str, ...]] = {}
    for agent, slot in _agent_slots(settings).items():
        rotated[agent] = keys[slot:] + keys[:slot]
    return rotated
