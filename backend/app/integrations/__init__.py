"""External system integrations (Steps 2 and 7).

Each module in this package wraps one external data source behind the shared
contract in :mod:`app.integrations.base`:

* a :class:`~app.integrations.base.Provenance` record travels with every returned
  object, carrying an ``is_mock`` flag so **simulated data can never be mistaken
  for live data**;
* a ``get_<name>_connector()`` factory returns the live adapter when a base URL
  is configured and a clearly labelled simulated adapter otherwise;
* the live adapters raise
  :class:`~app.integrations.base.IntegrationNotConfiguredError` rather than
  quietly falling back to sample data.

Connector modules
-----------------
* :mod:`app.integrations.weather` — severe-weather alerts.
* :mod:`app.integrations.news` — news headlines.
* :mod:`app.integrations.maritime_alerts` — maritime security / navigation alerts.
* :mod:`app.integrations.port_congestion` — port congestion.
* :mod:`app.integrations.tariffs` — duty / tariff rates.
* :mod:`app.integrations.suppliers` — supplier master data.
* :mod:`app.integrations.carriers` — carrier service catalogue.
* :mod:`app.integrations.shipment_tracking` — shipment tracking timelines.
* :mod:`app.integrations.mapping` — route distance / reference transit times.
* :mod:`app.integrations.sap` — **read-only** SAP master and transactional data,
  including material information.

SAP integration (Step 7)
------------------------
* :mod:`app.integrations.sap_profiles` — prepared profiles for S/4HANA, Business
  Accelerator Hub, BTP and Integration Suite.
* :mod:`app.integrations.sap_auth` — OAuth2 client-credentials tokens, separate
  read/write scopes and header redaction.
* :mod:`app.integrations.sap_write` — validated, approval-gated writes
  (shipment plan updates, inventory transfers, operational changes).

``app.integrations.base`` provides the shared helpers
(:class:`~app.integrations.base.Provenance`, :class:`~app.integrations.base.HttpJsonClient`,
the connector base classes and the error hierarchy) that every connector builds on.
"""
