"""Lead-Time Estimation Engine (Step 2).

Deterministic door-to-door transit-time estimation from distance and transport
mode, with optional caller-supplied handling, congestion, weather and
reliability buffers. No LLM is involved and no arithmetic happens inside a
prompt.

Assumptions
-----------
* Effective speed per mode is an *indicative planning value*
  (:data:`MODE_EFFECTIVE_SPEED_KM_PER_DAY`) that already folds in realistic
  routing, stops and average utilisation — it is not a vehicle top speed.
* ``transit_days = distance_km / MODE_EFFECTIVE_SPEED_KM_PER_DAY[mode]``.
* Handling defaults to the mode's fixed value
  (:data:`MODE_HANDLING_DAYS`) unless the caller supplies one.
* ``delay_days`` bundles the caller's congestion and weather delays:
  ``delay_days = congestion_days + weather_delay_days``.
* ``total_days = transit_days + handling_days + congestion_days + weather_delay_days``.
* ``adjusted_total_days = total_days + reliability_buffer_days`` — the buffer is
  a planned contingency the caller owns, kept separate from the raw estimate.
* The mode names are reused from :class:`app.tools.costing.TransportMode`
  (``Sea``, ``Rail``, ``Road``, ``Air``) so the costing and lead-time engines
  agree on the vocabulary.
"""

from __future__ import annotations

from typing import Optional

from app.tools.base import (
    EngineResult,
    require_choice,
    require_positive,
    round_units,
)
from app.tools.costing import TransportMode

#: Indicative effective speed (km/day) used to derive transit time, by mode.
MODE_EFFECTIVE_SPEED_KM_PER_DAY: dict[str, float] = {
    "Sea": 700.0,
    "Rail": 800.0,
    "Road": 900.0,
    "Air": 8000.0,
}

#: Default fixed handling time in days at origin/destination, by mode.
MODE_HANDLING_DAYS: dict[str, float] = {
    "Sea": 2.0,
    "Rail": 1.5,
    "Road": 0.5,
    "Air": 1.0,
}


class LeadTimeEstimate(EngineResult):
    """Deterministic transit-time estimate for one movement."""

    transport_mode: str
    distance_km: float
    transit_days: float
    handling_days: float
    delay_days: float
    total_days: float
    adjusted_total_days: float


def calculate_delivery_time(
    *,
    distance_km: float,
    transport_mode: str | TransportMode,
    handling_days: Optional[float] = None,
    congestion_days: float = 0.0,
    weather_delay_days: float = 0.0,
    reliability_buffer_days: float = 0.0,
) -> LeadTimeEstimate:
    """Return a deterministic :class:`LeadTimeEstimate` for one movement.

    Args:
        distance_km: Route distance in kilometres (> 0).
        transport_mode: One of :class:`~app.tools.costing.TransportMode`.
        handling_days: Origin/destination handling time. Defaults to the
            mode's value in :data:`MODE_HANDLING_DAYS` when omitted (>= 0).
        congestion_days: Expected congestion delay in days (>= 0).
        weather_delay_days: Expected weather delay in days (>= 0).
        reliability_buffer_days: Planned contingency added on top (> = 0).

    Raises:
        ToolInputError: The mode is unknown, the distance is not > 0, or any
            day input is negative / non-numeric.
    """
    distance = require_positive(distance_km, "distance_km")
    mode_name = require_choice(
        transport_mode, [mode.value for mode in TransportMode], "transport_mode"
    )
    if handling_days is None:
        handling = MODE_HANDLING_DAYS[mode_name]
    else:
        handling = require_positive(handling_days, "handling_days", allow_zero=True)
    congestion = require_positive(congestion_days, "congestion_days", allow_zero=True)
    weather = require_positive(weather_delay_days, "weather_delay_days", allow_zero=True)
    buffer = require_positive(
        reliability_buffer_days, "reliability_buffer_days", allow_zero=True
    )

    transit = distance / MODE_EFFECTIVE_SPEED_KM_PER_DAY[mode_name]
    delay = congestion + weather
    total = transit + handling + congestion + weather
    adjusted_total = total + buffer

    return LeadTimeEstimate(
        transport_mode=mode_name,
        distance_km=round_units(distance),
        transit_days=round_units(transit),
        handling_days=round_units(handling),
        delay_days=round_units(delay),
        total_days=round_units(total),
        adjusted_total_days=round_units(adjusted_total),
        assumptions=(
            f"Transit uses the indicative {mode_name.lower()} speed "
            f"{MODE_EFFECTIVE_SPEED_KM_PER_DAY[mode_name]} km/day.",
            f"Default handling time for {mode_name} is "
            f"{MODE_HANDLING_DAYS[mode_name]} day(s) unless supplied.",
            "Adjusted total adds the caller's reliability buffer to the total.",
        ),
    )
