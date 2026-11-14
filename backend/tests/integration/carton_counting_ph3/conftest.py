"""Fixtures for change plan 2026-11-12 Phase 3 (Carton Opening & Counting): reuse the P2-08 gate
fixtures (fake storage, test client, masters, actors with a Super Admin, products)."""

from tests.integration.phase2_gate.conftest import (  # noqa: F401 - pytest fixtures
    actors,
    admin,
    client,
    masters,
    products,
    storage,
)
