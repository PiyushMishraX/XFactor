"""SQLAlchemy declarative base shared by all X FACTOR ORM models.

No models are defined yet — domain models are added in later steps alongside
the agents and services that use them.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all ORM models."""
