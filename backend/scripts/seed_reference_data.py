"""Load the demo supply-chain reference data into PostgreSQL.

Run from the ``backend`` directory:

    ..\\..\\.venv\\Scripts\\python.exe -m scripts.seed_reference_data

The dataset is clearly labelled demo data (see ``app.services.reference_data``);
it exists so that shipment and supplier validation in Step 1 runs against real
database rows rather than in-memory fixtures.
"""

import sys
from pathlib import Path

# Allow `python scripts/seed_reference_data.py` as well as `-m scripts.`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.logging_config import configure_logging  # noqa: E402
from app.config.settings import get_settings  # noqa: E402
from app.database.session import get_engine, get_session_factory  # noqa: E402
from app.services.reference_data import ensure_schema, seed_reference_data  # noqa: E402


def main() -> int:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL, settings.LOG_JSON)

    print(f"Target database : {settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}")

    engine = get_engine()
    ensure_schema(engine)

    with get_session_factory()() as session:
        suppliers, shipments = seed_reference_data(session)

    print(f"Seeded          : {suppliers} suppliers, {shipments} shipments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
