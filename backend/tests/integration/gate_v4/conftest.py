"""Phase P2 / DEC-62 (gate form v4) fixtures: the fake storage and the test client using it."""

# P3: unboxing tests on gate v4 reuse the gate v4 actors / masters fixtures.
from tests.integration.gate_v4.test_gate_v4 import (  # noqa: F401 - pytest fixtures
    actors,
    masters,
)
from tests.integration.test_unboxing import (  # noqa: F401 - pytest fixtures
    client,
    storage,
)
