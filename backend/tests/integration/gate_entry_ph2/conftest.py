"""Fixtures for change plan 2026-11-12 Phase 2 (gate entry revamp): reuse the P2-08 gate fixtures
(fake storage, test client, masters, actors with a Super Admin)."""

from tests.integration.phase2_gate.conftest import (  # noqa: F401 - pytest fixtures
    actors,
    admin,
    client,
    masters,
    storage,
)
