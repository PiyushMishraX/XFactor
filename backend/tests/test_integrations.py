"""Tests for the Step 2 external-data connectors (``app.integrations``).

These tests pin down the two properties that matter most for the platform:

* **Every** simulated connector labels its data as simulated, so sample output can
  never be presented as live information.
* Simulated output is **deterministic** — the same query always yields the same
  answer, so the demo and the test-suite are repeatable.

The live adapters are exercised with ``httpx.MockTransport`` so the mapping from a
provider payload onto the platform's own models is verified without any network.
"""

from __future__ import annotations

import httpx
import pytest

from app.config.settings import Settings
from app.integrations.base import (
    HttpJsonClient,
    IntegrationNotConfiguredError,
    Provenance,
)
from app.integrations.carriers import CarrierService, get_carrier_connector
from app.integrations.mapping import RouteDistance, get_mapping_connector
from app.integrations.maritime_alerts import MaritimeSeverity, get_maritime_connector
from app.integrations.news import NewsArticle, get_news_connector
from app.integrations.port_congestion import (
    CongestionLevel,
    PortCongestion,
    congestion_level_for,
    get_port_congestion_connector,
)
from app.integrations.sap import (
    HttpSAPConnector,
    SAPInventoryItem,
    SAPShipment,
    SAPSupplier,
    SimulatedSAPConnector,
    get_sap_connector,
)
from app.integrations.shipment_tracking import TrackingEvent, get_shipment_tracking_connector
from app.integrations.suppliers import SupplierProfile, get_supplier_connector
from app.integrations.tariffs import TariffRate, get_tariff_connector
from app.integrations.weather import WeatherAlert, WeatherSeverity, get_weather_connector


def _blank(**overrides: object) -> Settings:
    """Settings with no integration URLs, independent of the local .env file."""
    return Settings(_env_file=None, **overrides)


def _mock_client(handler, *, base_url: str = "https://provider.test") -> HttpJsonClient:
    """An :class:`HttpJsonClient` wired to an in-process mock transport."""
    return HttpJsonClient(
        connector_name="test",
        base_url=base_url,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


# ---------------------------------------------------------------------------
# Factory behaviour: simulated by default, clearly labelled
# ---------------------------------------------------------------------------


_FACTORIES = (
    get_weather_connector,
    get_news_connector,
    get_maritime_connector,
    get_port_congestion_connector,
    get_tariff_connector,
    get_supplier_connector,
    get_carrier_connector,
    get_shipment_tracking_connector,
    get_mapping_connector,
)


@pytest.mark.parametrize("factory", _FACTORIES)
def test_factories_return_simulated_connectors_when_unconfigured(factory) -> None:
    connector = factory(_blank())
    assert connector.is_mock is True
    assert isinstance(connector.name, str) and connector.name


@pytest.mark.parametrize("factory", _FACTORIES)
def test_live_adapters_require_configuration(factory) -> None:
    """A blank configuration must yield the simulated adapter, never a silent live one."""
    assert factory(_blank()).is_mock is True


def test_provenance_label_marks_simulated_data() -> None:
    provenance = Provenance(source="Some feed", is_mock=True)
    assert provenance.label == "Some feed [SIMULATED]"
    assert Provenance(source="Some feed", is_mock=False).label == "Some feed"


def test_connector_provenance_is_marked_as_mock() -> None:
    connector = get_weather_connector(_blank())
    provenance = connector.provenance(endpoint="test")
    assert provenance.is_mock is True


def test_http_client_without_base_url_raises_not_configured() -> None:
    client = HttpJsonClient(connector_name="unconfigured", base_url="")
    assert client.configured is False
    with pytest.raises(IntegrationNotConfiguredError):
        client.get_json("/anything")


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_simulated_connectors_are_deterministic() -> None:
    """The same query yields the same values; only retrieval timestamps differ."""
    weather = get_weather_connector(_blank())
    first = weather.get_alerts(location="Shanghai")
    second = weather.get_alerts(location="Shanghai")
    assert [(a.event_type, a.severity, a.wind_speed_kmh) for a in first] == [
        (a.event_type, a.severity, a.wind_speed_kmh) for a in second
    ]

    congestion = get_port_congestion_connector(_blank())
    first_port = congestion.get_congestion(port="Lagos")
    second_port = congestion.get_congestion(port="Lagos")
    assert (first_port.vessels_waiting, first_port.average_wait_days, first_port.congestion_level) == (
        second_port.vessels_waiting,
        second_port.average_wait_days,
        second_port.congestion_level,
    )

    mapping = get_mapping_connector(_blank())
    first_route = mapping.get_route(origin="A", destination="B")
    second_route = mapping.get_route(origin="A", destination="B")
    assert (first_route.distance_km, first_route.transit_days_sea, first_route.is_estimated) == (
        second_route.distance_km,
        second_route.transit_days_sea,
        second_route.is_estimated,
    )


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------


def test_weather_known_location_returns_severe_alert() -> None:
    alerts = get_weather_connector(_blank()).get_alerts(location="Red Sea")
    assert len(alerts) == 1
    assert isinstance(alerts[0], WeatherAlert)
    assert alerts[0].severity is WeatherSeverity.SEVERE
    assert alerts[0].provenance.is_mock is True


def test_weather_calm_location_returns_no_alerts() -> None:
    assert get_weather_connector(_blank()).get_alerts(location="Rotterdam") == []


def test_weather_empty_location_is_rejected() -> None:
    with pytest.raises(ValueError):
        get_weather_connector(_blank()).get_alerts(location="  ")


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------


def test_news_matches_a_known_chokepoint() -> None:
    articles = get_news_connector(_blank()).get_headlines(query="Red Sea diversions")
    assert articles
    assert all(isinstance(article, NewsArticle) for article in articles)
    assert all(article.provenance.is_mock for article in articles)


def test_news_respects_limit_and_generates_for_unknown_query() -> None:
    connector = get_news_connector(_blank())
    assert len(connector.get_headlines(query="anything", limit=1)) == 1
    unknown = connector.get_headlines(query="Zzz nowhere lane")
    assert unknown and unknown[0].provenance.is_mock is True


def test_news_empty_query_is_rejected() -> None:
    with pytest.raises(ValueError):
        get_news_connector(_blank()).get_headlines(query="")


# ---------------------------------------------------------------------------
# Maritime alerts
# ---------------------------------------------------------------------------


def test_maritime_alerts_for_known_region() -> None:
    alerts = get_maritime_connector(_blank()).get_alerts(region="Red Sea")
    assert alerts
    assert alerts[0].severity is MaritimeSeverity.CRITICAL
    assert alerts[0].provenance.is_mock is True


def test_maritime_calm_region_returns_no_alerts() -> None:
    assert get_maritime_connector(_blank()).get_alerts(region="Rotterdam") == []


# ---------------------------------------------------------------------------
# Port congestion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("wait_days", "expected"),
    (
        (0.5, CongestionLevel.LOW),
        (1.0, CongestionLevel.LOW),
        (1.5, CongestionLevel.MODERATE),
        (3.0, CongestionLevel.MODERATE),
        (4.0, CongestionLevel.HIGH),
        (7.0, CongestionLevel.HIGH),
        (7.5, CongestionLevel.SEVERE),
    ),
)
def test_congestion_level_thresholds(wait_days: float, expected: CongestionLevel) -> None:
    assert congestion_level_for(wait_days) is expected


def test_congestion_returns_exactly_one_record() -> None:
    record = get_port_congestion_connector(_blank()).get_congestion(port="Shanghai")
    assert isinstance(record, PortCongestion)
    assert record.congestion_level is CongestionLevel.HIGH
    assert record.provenance.is_mock is True


# ---------------------------------------------------------------------------
# Tariffs
# ---------------------------------------------------------------------------


def test_tariff_total_is_duty_plus_levy() -> None:
    rate = get_tariff_connector(_blank()).get_rate(
        origin_country="China", destination_country="Germany", hs_code="8542.31"
    )
    assert isinstance(rate, TariffRate)
    assert rate.total_rate_percent == pytest.approx(
        rate.duty_rate_percent + rate.additional_levy_percent
    )
    assert rate.duty_rate_percent == 4.7
    assert rate.provenance.is_mock is True


def test_tariff_requires_lane_and_code() -> None:
    with pytest.raises(ValueError):
        get_tariff_connector(_blank()).get_rate(
            origin_country="China", destination_country="", hs_code="8542"
        )


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------


def test_supplier_profiles_match_the_demo_masters() -> None:
    connector = get_supplier_connector(_blank())
    profiles = connector.list_profiles()
    assert [profile.supplier_id for profile in profiles] == [
        "SUP001",
        "SUP002",
        "SUP003",
        "SUP004",
        "SUP005",
    ]
    assert all(isinstance(profile, SupplierProfile) for profile in profiles)
    assert all(profile.provenance.is_mock for profile in profiles)


def test_supplier_unknown_id_returns_none() -> None:
    assert get_supplier_connector(_blank()).get_profile(supplier_id="SUP999") is None


# ---------------------------------------------------------------------------
# Carriers
# ---------------------------------------------------------------------------


def test_carrier_catalogue_filters_by_mode() -> None:
    connector = get_carrier_connector(_blank())
    sea = connector.list_services(transport_mode="Sea")
    assert sea and all(service.transport_mode == "Sea" for service in sea)
    assert all(isinstance(service, CarrierService) for service in sea)

    assert connector.list_services(transport_mode="Air")
    assert len(connector.list_services()) >= len(sea)


# ---------------------------------------------------------------------------
# Shipment tracking
# ---------------------------------------------------------------------------


def test_tracking_known_shipment_has_timeline() -> None:
    events = get_shipment_tracking_connector(_blank()).get_events(shipment_id="SH005")
    assert events
    assert all(isinstance(event, TrackingEvent) for event in events)
    assert events[-1].status.value == "Delayed"
    assert all(event.provenance.is_mock for event in events)


def test_tracking_unknown_shipment_is_derived_deterministically() -> None:
    connector = get_shipment_tracking_connector(_blank())
    first = connector.get_events(shipment_id="SH999")
    second = connector.get_events(shipment_id="SH999")
    assert [(e.status, e.location, e.description) for e in first] == [
        (e.status, e.location, e.description) for e in second
    ]


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------


def test_mapping_known_lane_is_not_estimated() -> None:
    route = get_mapping_connector(_blank()).get_route(origin="Mumbai", destination="Rotterdam")
    assert isinstance(route, RouteDistance)
    assert route.is_estimated is False
    assert route.distance_km == 11000.0
    assert route.provenance.is_mock is True


def test_mapping_reverse_and_unknown_lanes_are_estimated() -> None:
    connector = get_mapping_connector(_blank())
    reverse = connector.get_route(origin="Rotterdam", destination="Mumbai")
    assert reverse.is_estimated is True
    assert reverse.distance_km == 11000.0

    unknown = connector.get_route(origin="Nowhere", destination="Elsewhere")
    assert unknown.is_estimated is True
    assert unknown.distance_km > 0


# ---------------------------------------------------------------------------
# SAP (read-only)
# ---------------------------------------------------------------------------


def test_sap_reads_demo_masters_and_inventory() -> None:
    sap = SimulatedSAPConnector()
    assert isinstance(sap.get_shipment(shipment_id="SH001"), SAPShipment)
    assert isinstance(sap.get_supplier(supplier_id="SUP003"), SAPSupplier)
    assert isinstance(sap.get_inventory_item(material_id="MAT-ELEC-003"), SAPInventoryItem)
    assert len(sap.list_suppliers()) == 5
    assert sap.list_purchase_orders(supplier_id="SUP003")
    assert sap.get_shipment(shipment_id="SH999") is None


def test_sap_records_are_labelled_simulated() -> None:
    sap = SimulatedSAPConnector()
    assert sap.is_mock is True
    assert sap.list_shipments()[0].provenance.is_mock is True


@pytest.mark.parametrize(
    "forbidden",
    (
        "create_shipment",
        "update_shipment",
        "delete_shipment",
        "create_purchase_order",
        "post_goods_receipt",
        "write",
        "execute",
    ),
)
def test_sap_connector_exposes_no_write_operations(forbidden: str) -> None:
    assert not hasattr(SimulatedSAPConnector(), forbidden)


def test_sap_factory_returns_simulated_under_mock_mode() -> None:
    connector = get_sap_connector(_blank(SAP_USE_MOCK=True))
    assert isinstance(connector, SimulatedSAPConnector)
    assert connector.is_mock is True


def test_sap_factory_raises_when_mock_disabled_and_unconfigured() -> None:
    with pytest.raises(IntegrationNotConfiguredError):
        get_sap_connector(_blank(SAP_USE_MOCK=False))


def test_sap_factory_returns_live_adapter_when_configured() -> None:
    settings = _blank(
        SAP_USE_MOCK=False,
        SAP_BASE_URL="https://sap.example.test",
        SAP_CLIENT_ID="client",
        SAP_CLIENT_SECRET="secret",
    )
    connector = get_sap_connector(settings)
    assert isinstance(connector, HttpSAPConnector)
    assert connector.is_mock is False
    assert connector.configured is True


# ---------------------------------------------------------------------------
# Live adapters: provider payload -> platform model
# ---------------------------------------------------------------------------


def test_live_weather_maps_provider_payload() -> None:
    from app.integrations.weather import LiveWeatherConnector

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["location"] == "Red Sea"
        return httpx.Response(
            200,
            json={
                "alerts": [
                    {
                        "event_type": "High winds",
                        "headline": "Gale warning",
                        "severity": "Warning",
                        "wind_speed_kmh": 65,
                    }
                ]
            },
        )

    connector = LiveWeatherConnector(settings=_blank(), client=_mock_client(handler))
    alerts = connector.get_alerts(location="Red Sea")
    assert len(alerts) == 1
    assert alerts[0].severity is WeatherSeverity.WARNING
    assert alerts[0].provenance.is_mock is False


def test_live_tracking_maps_provider_payload() -> None:
    from app.integrations.shipment_tracking import LiveShipmentTrackingConnector

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "status": "Customs Hold",
                    "location": "Singapore",
                    "occurred_at": "2026-11-20T09:00:00+00:00",
                    "description": "Held for inspection.",
                }
            ],
        )

    connector = LiveShipmentTrackingConnector(settings=_blank(), client=_mock_client(handler))
    events = connector.get_events(shipment_id="SH008")
    assert len(events) == 1
    assert events[0].status.value == "Customs Hold"
    assert events[0].provenance.is_mock is False


def test_live_connector_retries_retryable_status_then_succeeds() -> None:
    from app.integrations.carriers import LiveCarrierConnector

    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json=[{"carrier": "Maersk", "transport_mode": "Sea"}])

    client = HttpJsonClient(
        connector_name="carriers",
        base_url="https://provider.test",
        backoff_seconds=0.0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    connector = LiveCarrierConnector(settings=_blank(), client=client)
    services = connector.list_services()
    assert attempts["count"] == 2
    assert services[0].carrier == "Maersk"
    assert services[0].provenance.is_mock is False
