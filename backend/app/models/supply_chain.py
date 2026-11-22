"""ORM models for the supply-chain reference data the agents reason over.

Only the two entities Step 1 needs are defined: shipments and the suppliers that
fulfil them. Additional SAP-domain entities arrive in later steps.
"""

from __future__ import annotations

from decimal import Decimal
from typing import List

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class Supplier(Base):
    """A supplier that fulfils one or more shipments."""

    __tablename__ = "suppliers"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    country: Mapped[str] = mapped_column(String(80), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    risk_tier: Mapped[str] = mapped_column(String(16), nullable=False)

    shipments: Mapped[List["Shipment"]] = relationship(back_populates="supplier")


class Shipment(Base):
    """A physical movement of goods, including the route it follows.

    ``route`` holds the human-readable lane (for example
    ``"Mumbai -> Rotterdam via Suez Canal, Red Sea"``) so that a disruption
    reported against a chokepoint such as the Red Sea can be matched to the
    shipments that actually transit it.
    """

    __tablename__ = "shipments"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    origin: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    destination: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    route: Mapped[str] = mapped_column(String(240), nullable=False)
    transport_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    carrier: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    cargo: Mapped[str] = mapped_column(String(120), nullable=False)
    value_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.id"), nullable=False, index=True)
    supplier: Mapped[Supplier] = relationship(back_populates="shipments")
