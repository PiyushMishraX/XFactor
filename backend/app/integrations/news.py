"""News API connector (Step 2).

Returns recent news headlines for a free-text query so the sensing agent can
corroborate a disruption report with published coverage. The live variant calls a
configured HTTP JSON provider; when no provider is configured the factory returns
:class:`SimulatedNewsConnector`, whose articles are clearly marked
``is_mock=True``.

Assumptions
-----------
* The provider exposes ``GET {base}/search?q=<query>&limit=<n>`` returning a JSON
  object with an ``articles`` array (the most common shape) or a bare array.
* Sample headlines cover the demo chokepoints (Red Sea, Suez Canal, Shanghai,
  Malacca Strait, Panama Canal). For any other query the sample is derived
  deterministically from the query text via :func:`stable_seed` — never randomly.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence

from pydantic import BaseModel

from app.config.settings import Settings, get_settings
from app.integrations.base import (
    HttpConnector,
    HttpJsonClient,
    MockConnector,
    Provenance,
    stable_seed,
    utc_now,
)

logger = logging.getLogger(__name__)


class NewsArticle(BaseModel):
    """A single news item returned for a query."""

    title: str
    summary: str
    source: str
    url: Optional[str] = None
    published_at: str
    location: Optional[str] = None
    provenance: Provenance


class NewsConnector(Protocol):
    """Lookup interface used by the agents."""

    name: str

    @property
    def is_mock(self) -> bool: ...

    def get_headlines(self, *, query: str, limit: int = 10) -> List[NewsArticle]:
        """Return up to ``limit`` recent headlines for ``query``."""
        ...


# Sample headlines for the demo chokepoints. Keys are lower-cased query keywords.
_SAMPLE_HEADLINES: Mapping[str, Sequence[Dict[str, Any]]] = {
    "red sea": (
        {
            "title": "Red Sea transits fall again as insurers widen war-risk zone",
            "summary": "Carriers report a further drop in Suez transits as war-risk premiums rise.",
            "source": "Reuters",
            "location": "Red Sea",
        },
        {
            "title": "Container rates on Asia-Europe routes climb on Red Sea diversion",
            "summary": "Spot rates jump as vessels reroute around the Cape of Good Hope.",
            "source": "Lloyd's List",
            "location": "Red Sea",
        },
    ),
    "suez": (
        {
            "title": "Suez Canal Authority reports lower daily transits",
            "summary": "Daily transits decline year on year as shippers avoid the corridor.",
            "source": "Al Ahram",
            "location": "Suez Canal",
        },
    ),
    "shanghai": (
        {
            "title": "Shanghai port braces for typhoon, berthing windows reshuffled",
            "summary": "Terminals suspend some operations ahead of a forecast typhoon.",
            "source": "Xinhua",
            "location": "Shanghai",
        },
    ),
    "malacca": (
        {
            "title": "Malacca Strait piracy incidents tick up in first half",
            "summary": "Regional navies increase patrols after a rise in boardings.",
            "source": "The Straits Times",
            "location": "Malacca Strait",
        },
    ),
    "panama": (
        {
            "title": "Panama Canal authority trims daily booking slots",
            "summary": "Drought-driven restrictions continue to cap daily transits.",
            "source": "Reuters",
            "location": "Panama Canal",
        },
    ),
}


class SimulatedNewsConnector(MockConnector):
    """Clearly labelled sample news feed (no live provider configured)."""

    name = "news"
    provider = "X FACTOR simulated news feed"

    def get_headlines(self, *, query: str, limit: int = 10) -> List[NewsArticle]:
        text = (query or "").strip()
        if not text:
            raise ValueError("query must be a non-empty string")
        take = max(1, int(limit))

        provenance = self.provenance(endpoint="simulated://news/search")
        templates = self._templates_for(text)
        now = utc_now()

        articles: List[NewsArticle] = []
        for index, template in enumerate(templates[:take]):
            articles.append(
                NewsArticle(
                    title=str(template["title"]),
                    summary=str(template["summary"]),
                    source=str(template["source"]),
                    url=template.get("url"),
                    published_at=(now - timedelta(hours=index * 6)).isoformat(),
                    location=template.get("location"),
                    provenance=provenance,
                )
            )
        return articles

    @staticmethod
    def _templates_for(query: str) -> Sequence[Dict[str, Any]]:
        """Match the query against known chokepoints, else synthesise a sample."""
        key = query.strip().lower()
        matches: List[Dict[str, Any]] = []
        for keyword, templates in _SAMPLE_HEADLINES.items():
            if keyword in key:
                matches.extend(templates)
        if matches:
            return matches

        seed = stable_seed("news", key)
        return (
            {
                "title": f"Simulated coverage: logistics pressure reported around {query.strip().title()}",
                "summary": "Deterministic sample headline generated for an unmapped query.",
                "source": "X FACTOR sample wire",
                "location": None,
            },
            {
                "title": f"Analysts flag lead-time risk on {query.strip().title()} lanes",
                "summary": f"Sample analysis #{seed % 1000} of the queried corridor.",
                "source": "X FACTOR sample wire",
                "location": None,
            },
        )


class LiveNewsConnector(HttpConnector):
    """Live news provider adapter (requires NEWS_API_BASE_URL)."""

    name = "news"
    provider = "Live news API"

    def __init__(self, settings: Optional[Settings] = None, client: Optional[HttpJsonClient] = None) -> None:
        settings = settings or get_settings()
        super().__init__(
            client
            or HttpJsonClient(
                connector_name=self.name,
                base_url=settings.NEWS_API_BASE_URL,
                api_key=settings.NEWS_API_KEY,
                timeout=settings.INTEGRATION_TIMEOUT_SECONDS,
                max_attempts=settings.INTEGRATION_MAX_ATTEMPTS,
            )
        )

    def get_headlines(self, *, query: str, limit: int = 10) -> List[NewsArticle]:
        payload = self.client.get_json("/search", params={"q": query, "limit": limit})
        records = payload.get("articles", []) if isinstance(payload, dict) else payload
        provenance = self.provenance(endpoint=f"{self.client.base_url}/search")
        return [_map_article(record, provenance) for record in records[: max(1, int(limit))]]


def _map_article(record: Mapping[str, Any], provenance: Provenance) -> NewsArticle:
    """Map one provider record onto the platform's own model."""
    return NewsArticle(
        title=str(record.get("title") or "Untitled"),
        summary=str(record.get("summary") or record.get("description") or ""),
        source=str(record.get("source") or record.get("provider") or "unknown"),
        url=record.get("url"),
        published_at=str(record.get("published_at") or record.get("publishedAt") or utc_now().isoformat()),
        location=record.get("location"),
        provenance=provenance,
    )


def get_news_connector(settings: Optional[Settings] = None) -> NewsConnector:
    """Return the live connector when configured, otherwise the simulated one."""
    live = LiveNewsConnector(settings)
    if live.configured:
        return live
    logger.info("News API not configured — using clearly labelled simulated feed.")
    return SimulatedNewsConnector()
