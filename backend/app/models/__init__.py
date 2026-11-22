"""SQLAlchemy ORM models (database tables).

Importing this package registers every model on ``Base.metadata``, which is what
``Base.metadata.create_all`` and the reference-data seed script rely on.
"""

from app.models.approvals import ApprovalRequestRow
from app.models.supply_chain import Shipment, Supplier

__all__ = ["ApprovalRequestRow", "Shipment", "Supplier"]
