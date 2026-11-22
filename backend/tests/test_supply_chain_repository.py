"""Integration tests for shipment/supplier validation against PostgreSQL.

These are the only Step 1 tests that touch the real database. They skip cleanly
when PostgreSQL is unreachable or the demo reference data has not been seeded, so
the suite still runs on a machine without a database.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.session import check_database_connection, get_session_factory
from app.models.supply_chain import Shipment
from app.services.supply_chain_repository import (
    PostgresSupplyChainRepository,
    location_patterns,
    normalise_reference_ids,
)

RED_SEA_SHIPMENTS = {"SH001", "SH002", "SH003", "SH005", "SH010"}


@pytest.fixture(scope="module")
def session() -> Session:
    if not check_database_connection():
        pytest.skip("PostgreSQL is unreachable; skipping database-backed tests.")

    factory = get_session_factory()
    with factory() as db_session:
        try:
            shipment_count = db_session.scalar(select(func.count()).select_from(Shipment))
        except SQLAlchemyError as exc:  # tables not created yet
            pytest.skip(f"Reference tables are unavailable: {exc}")

        if not shipment_count:
            pytest.skip(
                "Reference data is not seeded; run "
                "'python -m scripts.seed_reference_data' first."
            )
        yield db_session


@pytest.fixture
def repository(session: Session) -> PostgresSupplyChainRepository:
    return PostgresSupplyChainRepository(session)


def test_known_shipment_ids_are_validated(repository: PostgresSupplyChainRepository) -> None:
    snapshot = repository.snapshot(
        shipment_ids=["SH001", "SH002"], supplier_ids=[], locations=[]
    )

    assert [shipment.id for shipment in snapshot.shipments_by_reference] == ["SH001", "SH002"]
    assert snapshot.unknown_shipment_ids == ()
    assert snapshot.shipments_by_reference[0].origin == "Mumbai"
    assert snapshot.shipments_by_reference[0].supplier_id == "SUP001"


def test_unknown_references_are_reported_not_silently_dropped(
    repository: PostgresSupplyChainRepository,
) -> None:
    snapshot = repository.snapshot(
        shipment_ids=["sh001", "SH999"], supplier_ids=["SUP404"], locations=[]
    )

    # Lower-case input is normalised, the real id survives, the fake one is reported.
    assert [shipment.id for shipment in snapshot.shipments_by_reference] == ["SH001"]
    assert snapshot.unknown_shipment_ids == ("SH999",)
    assert snapshot.unknown_supplier_ids == ("SUP404",)


def test_red_sea_disruption_maps_to_the_shipments_that_transit_it(
    repository: PostgresSupplyChainRepository,
) -> None:
    snapshot = repository.snapshot(
        shipment_ids=[], supplier_ids=[], locations=["Red Sea", "Bab-el-Mandeb"]
    )

    assert {shipment.id for shipment in snapshot.shipments_by_location} == RED_SEA_SHIPMENTS
    assert all(
        "Red Sea" in shipment.route for shipment in snapshot.shipments_by_location
    )


def test_supplier_country_match_exposes_that_suppliers_shipments(
    repository: PostgresSupplyChainRepository,
) -> None:
    snapshot = repository.snapshot(shipment_ids=[], supplier_ids=[], locations=["China"])

    assert [supplier.id for supplier in snapshot.suppliers_by_location] == ["SUP003"]
    # SUP003 fulfils SH003, SH004 and SH010.
    assert {shipment.id for shipment in snapshot.shipments_by_supplier} == {
        "SH003",
        "SH004",
        "SH010",
    }
    assert {shipment.id for shipment in snapshot.shipments} == {"SH003", "SH004", "SH010"}


def test_a_supplier_reference_also_exposes_its_shipments(
    repository: PostgresSupplyChainRepository,
) -> None:
    snapshot = repository.snapshot(shipment_ids=[], supplier_ids=["SUP003"], locations=[])

    assert [supplier.id for supplier in snapshot.suppliers_by_reference] == ["SUP003"]
    assert {shipment.id for shipment in snapshot.shipments} == {"SH003", "SH004", "SH010"}


def test_shipments_are_never_duplicated_across_match_sources(
    repository: PostgresSupplyChainRepository,
) -> None:
    snapshot = repository.snapshot(
        shipment_ids=["SH010"], supplier_ids=["SUP003"], locations=["Shenzhen", "Red Sea"]
    )

    ids = snapshot.shipment_ids
    assert len(ids) == len(set(ids))
    assert "SH010" in ids


def test_unmatched_location_yields_no_shipments(
    repository: PostgresSupplyChainRepository,
) -> None:
    snapshot = repository.snapshot(
        shipment_ids=[], supplier_ids=[], locations=["Unexplored Fictional Region"]
    )

    assert snapshot.shipments == ()
    assert snapshot.suppliers == ()


def test_empty_inputs_return_an_empty_snapshot(
    repository: PostgresSupplyChainRepository,
) -> None:
    snapshot = repository.snapshot(shipment_ids=[], supplier_ids=[], locations=[])

    assert snapshot.shipments == ()
    assert snapshot.suppliers == ()
    assert snapshot.unknown_shipment_ids == ()


# -- pure helpers ------------------------------------------------------------


def test_normalise_reference_ids_trims_uppercases_and_deduplicates() -> None:
    assert normalise_reference_ids([" sh001 ", "SH001", "sh002", "", "   "]) == [
        "SH001",
        "SH002",
    ]


def test_location_patterns_skip_strings_too_short_to_match_safely() -> None:
    assert location_patterns(["US", "a", " Red Sea "]) == ["%Red Sea%"]
