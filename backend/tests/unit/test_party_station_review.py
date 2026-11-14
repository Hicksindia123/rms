"""Party station review helpers (backend/scripts/import_parties.py).

Change plan 2026-11-12 Phase 1 step 4 · DEC-37: the Decision column of party_station_review.csv
(ADD | ADD:<name> | MAP:<existing station> | SKIP) drives seed_stations.sql and the re-import.
"""

from __future__ import annotations

import importlib.util
import sys
from collections import defaultdict
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "import_parties.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("import_parties_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ip = _load()

REVIEW_HEADER = (
    "State,Station,Rows,Resolved State,Suggested Action,Closest Existing Station,Similarity,"
    "Decision\n"
)


def _review(tmp_path: Path, rows: str) -> Path:
    p = tmp_path / "review.csv"
    p.write_text(REVIEW_HEADER + rows, encoding="utf-8-sig")
    return p


def _masters() -> tuple[dict[str, tuple[str, str]], dict[str, dict[str, tuple[str, str]]]]:
    states = {"HARYANA": ("s-hr", "Haryana")}
    exact: dict[str, dict[str, tuple[str, str]]] = defaultdict(dict)
    exact["s-hr"]["GURUGRAM"] = ("st-ggn", "Gurugram")
    return states, exact


def test_station_name_title_cases_upper_case_input() -> None:
    assert ip._station_name("DEHRI ON SONE") == "Dehri On Sone"
    assert ip._station_name("DOMBIVLI (EAST)") == "Dombivli (East)"
    assert ip._station_name("Kharar") == "Kharar"  # mixed case is kept


def test_map_decision_resolves_to_existing_station(tmp_path: Path) -> None:
    states, exact = _masters()
    review = _review(tmp_path, "HARYANA,GURGAON,13,Haryana,ADD,Gurugram,0.67,MAP:Gurugram\n")
    mapping = ip._load_station_map(review, states, exact)
    assert mapping == {("s-hr", "GURGAON"): ("st-ggn", "Gurugram")}


def test_skip_and_add_decisions_are_not_mappings(tmp_path: Path) -> None:
    states, exact = _masters()
    review = _review(
        tmp_path,
        "HARYANA,BALLABHGARH,2,Haryana,ADD,,,ADD\nHARYANA,X,1,Haryana,ADD,,,SKIP\n",
    )
    assert ip._load_station_map(review, states, exact) == {}


def test_map_to_unknown_station_is_rejected(tmp_path: Path) -> None:
    """A MAP target must already exist: never silently drop or guess a station."""
    states, exact = _masters()
    review = _review(tmp_path, "HARYANA,HISSAR,2,Haryana,MAP?,Hisar,0.86,MAP:Hisar\n")
    with pytest.raises(SystemExit, match="MAP target 'Hisar' not found"):
        ip._load_station_map(review, states, exact)


def test_review_file_without_decision_column_is_rejected(tmp_path: Path) -> None:
    p = tmp_path / "bad.csv"
    p.write_text("State,Station\nHARYANA,HISSAR\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="no Decision column"):
        ip._read_review(p)
