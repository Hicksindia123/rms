"""Party master bulk import (CSV) and go-live seed export.

    uv run python scripts/import_parties.py import "Parties by State-Location.csv"
    uv run python scripts/import_parties.py export-seed
    uv run python scripts/import_parties.py review-stations ../party_import_exceptions.csv
    uv run python scripts/import_parties.py station-review-seed ../party_station_review.csv
    uv run python scripts/import_parties.py station-review-seed ../party_station_review.csv --apply
    uv run python scripts/import_parties.py import ../party_import_exceptions.csv
        --station-review ../party_station_review.csv      (one command line)

`review-stations` and `station-review-seed` without --apply are dry runs. Station workflow
(DEC-37): `review-stations` writes party_station_review.csv; the business fills its Decision
column (ADD | ADD:<name> | MAP:<existing station> | SKIP); `station-review-seed --apply` writes
and loads supabase/seed_stations.sql; `import --station-review` re-imports the exception rows
(keeping their original CSV row numbers); `export-seed` refreshes seed_parties.sql.

`import` reads a CSV with the columns State, Station, Client Name and inserts every party whose
state and station resolve against the active state/station masters (DEC-02). Rows that do not
resolve are not inserted; they are written to `party_import_exceptions.csv` in the repository root
with a reason.
Exact duplicates (same name, state and station, in the CSV or already in the DB) are skipped.

Station matching ignores case and extra spaces, and also accepts a name shown in brackets in the
master: "VIJAYAWADA" resolves to "NTR (Vijayawada)", "GUWAHATI" to "Kamrup Metropolitan (Guwahati)".
A name that resolves to more than one station is reported as ambiguous, never guessed.

Imported parties get system codes `PTY-00001`, `PTY-00002`, ... continuing from the highest existing
`PTY-` code. Like the `PROV-` codes (docs/DECISIONS.md, P2-02) these are system identifiers, not a
business number series.

`export-seed` writes every `PTY-` party in the DB to `supabase/seed_parties.sql`, keyed by state and
station *names*, so it applies to any database built from the migrations (`supabase db reset` loads
it via config.toml; at go-live run it with psql). The seed is idempotent (ON CONFLICT (code) DO
NOTHING) and fails loudly if a state/station pair is missing in the target DB.

The database defaults to the local Supabase superuser; pass --db-url (or set
RMS_IMPORT_DATABASE_URL) for another database.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

REPO_ROOT = Path(__file__).resolve().parents[2]
EXCEPTIONS_FILE = REPO_ROOT / "party_import_exceptions.csv"
SEED_FILE = REPO_ROOT / "supabase" / "seed_parties.sql"
LOCAL_SUPERUSER_URL = "postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres"
CODE_PREFIX = "PTY-"


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).upper()


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


StationRef = tuple[str, str]  # (id, name); also used for states
ExactIndex = dict[str, dict[str, StationRef]]  # state_id -> normalised station name -> station
AliasIndex = dict[str, dict[str, set[StationRef]]]  # state_id -> bracketed alias -> stations


def _load_masters(conn: Connection) -> tuple[dict[str, StationRef], ExactIndex, AliasIndex]:
    states = {
        _norm(name): (str(sid), name)
        for sid, name in conn.execute(text("select id, name from public.states where is_active"))
    }
    exact: ExactIndex = defaultdict(dict)
    alias: AliasIndex = defaultdict(lambda: defaultdict(set))
    rows = conn.execute(text("select id, state_id, name from public.stations where is_active"))
    for st_id, state_id, name in rows:
        ref = (str(st_id), name)
        exact[str(state_id)][_norm(name)] = ref
        bracketed = re.match(r"^(.*?)\s*\((.*)\)\s*$", name)
        if bracketed:
            alias[str(state_id)][_norm(bracketed.group(1))].add(ref)
            for part in bracketed.group(2).split("/"):
                alias[str(state_id)][_norm(part)].add(ref)
    return states, exact, alias


def _load_station_map(
    review_path: Path, states: dict[str, StationRef], exact: ExactIndex
) -> dict[tuple[str, str], StationRef]:
    """MAP:<station> decisions of a station review file (DEC-37).

    Returns (state_id, NORM station) -> station.

    A MAP target must exist under the same state (an ADD station must be loaded first)."""
    mapping: dict[tuple[str, str], StationRef] = {}
    for row in _read_review(review_path):
        decision = row["Decision"]
        if not decision.upper().startswith("MAP:"):
            continue
        state = states.get(_norm(row["State"]))
        target = decision[4:].strip()
        hit = exact[state[0]].get(_norm(target)) if state else None
        if state is None or hit is None:
            raise SystemExit(
                f"{review_path.name}: MAP target '{target}' not found under state "
                f"'{row['State']}' (load the ADD stations first)"
            )
        mapping[(state[0], _norm(row["Station"]))] = hit
    return mapping


def cmd_import(conn: Connection, csv_path: Path, station_review: Path | None = None) -> int:
    states, exact, alias = _load_masters(conn)
    station_map = _load_station_map(station_review, states, exact) if station_review else {}
    existing = {
        (str(r[0]), str(r[1]), _norm(r[2]))
        for r in conn.execute(text("select state_id, station_id, name from public.parties"))
    }
    max_code = conn.execute(
        text(
            "select coalesce(max(substr(code, :n)::int), 0) from public.parties"
            " where code ~ ('^' || :p || '[0-9]+$')"
        ),
        {"n": len(CODE_PREFIX) + 1, "p": CODE_PREFIX},
    ).scalar_one()

    to_insert: list[dict[str, str]] = []
    exceptions: list[list[object]] = []
    duplicates = 0
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for file_row_no, row in enumerate(csv.DictReader(f), start=2):
            # Re-importing an exceptions file keeps the row number of the original CSV.
            original = (row.get("CSV Row") or "").strip()
            row_no = int(original) if original.isdigit() else file_row_no
            state_raw, station_raw = _clean(row["State"]), _clean(row["Station"])
            name = _clean(row["Client Name"])
            if not name:
                exceptions.append([row_no, state_raw, station_raw, name, "Client Name is blank"])
                continue
            state = states.get(_norm(state_raw))
            if state is None:
                exceptions.append(
                    [row_no, state_raw, station_raw, name, "State not found in State master"]
                )
                continue
            state_id, state_name = state
            hit = exact[state_id].get(_norm(station_raw)) or station_map.get(
                (state_id, _norm(station_raw))
            )
            if hit is None:
                candidates = alias[state_id].get(_norm(station_raw), set())
                if len(candidates) > 1:
                    names = " | ".join(sorted(c[1] for c in candidates))
                    exceptions.append(
                        [row_no, state_raw, station_raw, name, f"Station ambiguous: {names}"]
                    )
                    continue
                hit = next(iter(candidates), None)
            if hit is None:
                exceptions.append(
                    [
                        row_no,
                        state_raw,
                        station_raw,
                        name,
                        f"Station not found under state '{state_name}'",
                    ]
                )
                continue
            key = (state_id, hit[0], _norm(name))
            if key in existing:
                duplicates += 1
                continue
            existing.add(key)
            to_insert.append(
                {
                    "code": f"{CODE_PREFIX}{max_code + len(to_insert) + 1:05d}",
                    "name": name,
                    "state_id": state_id,
                    "station_id": hit[0],
                }
            )

    if to_insert:
        conn.execute(
            text(
                "insert into public.parties (code, name, state_id, station_id)"
                " values (:code, :name, :state_id, :station_id)"
            ),
            to_insert,
        )

    with EXCEPTIONS_FILE.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["CSV Row", "State", "Station", "Client Name", "Reason"])
        writer.writerows(exceptions)

    print(f"inserted={len(to_insert)} exceptions={len(exceptions)} duplicates_skipped={duplicates}")
    print(f"exceptions file: {EXCEPTIONS_FILE}")
    print("Run `export-seed` to refresh supabase/seed_parties.sql.")
    return 0


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def cmd_export_seed(conn: Connection) -> int:
    rows = conn.execute(
        text(
            """
            select p.code, p.name, s.name, st.name
              from public.parties p
              join public.states s on s.id = p.state_id
              join public.stations st on st.id = p.station_id
             where p.code ~ ('^' || :p || '[0-9]+$')
             order by p.code
            """
        ),
        {"p": CODE_PREFIX},
    ).all()
    if not rows:
        print(f"No {CODE_PREFIX} parties in the database; seed not written.", file=sys.stderr)
        return 1

    values = ",\n".join(f"  ({', '.join(_sql_literal(v) for v in row)})" for row in rows)
    # Written to a file, not executed here; every value goes through _sql_literal.
    SEED_FILE.write_text(
        f"""-- Party master: bulk-imported parties ({len(rows)} rows).
-- GENERATED by backend/scripts/import_parties.py export-seed. Do not edit by hand:
-- import into the DB, then re-export.
--
-- Loaded after seed.sql by `supabase db reset` (config.toml [db.seed]). At go-live:
--   psql "$DB_URL" -v ON_ERROR_STOP=1 -1 -f supabase/seed_parties.sql
-- Idempotent: ON CONFLICT (code) DO NOTHING never overwrites admin edits to an existing party.
-- States/stations are resolved by name; a missing pair aborts the load (no silent drops).

drop table if exists pg_temp._seed_parties;
create temporary table _seed_parties (code text, name text, state text, station text);

insert into _seed_parties (code, name, state, station) values
{values};

do $$
declare
  missing text;
begin
  select string_agg(distinct format('%s / %s', v.state, v.station), '; ')
    into missing
    from _seed_parties v
    left join public.states s on s.name = v.state
    left join public.stations st on st.state_id = s.id and st.name = v.station
   where st.id is null;
  if missing is not null then
    raise exception 'seed_parties: state/station not in masters: %', missing;
  end if;
end
$$;

insert into public.parties (code, name, state_id, station_id)
select v.code, v.name, s.id, st.id
  from _seed_parties v
  join public.states s on s.name = v.state
  join public.stations st on st.state_id = s.id and st.name = v.station
on conflict (code) do nothing;

drop table pg_temp._seed_parties;
""",  # noqa: S608
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {len(rows)} parties to {SEED_FILE}")
    return 0


REVIEW_FILE = REPO_ROOT / "party_station_review.csv"


def _tokens(value: str) -> list[str]:
    return [t for t in re.split(r"[^A-Z0-9]+", _norm(value)) if t]


def _word_match(a: str, b: str) -> bool:
    """True when `a` (spaces ignored) equals a contiguous run of whole words of `b`, e.g.
    GOPAL GANJ ~ Gopalganj, BENGALURU ~ Bengaluru Urban — but UNA !~ Junagadh, MAU !~ Mauranipur."""
    target = "".join(_tokens(a))
    words = _tokens(b)
    if len(target) < 3:
        return False
    for i in range(len(words)):
        run = ""
        for w in words[i:]:
            run += w
            if run == target:
                return True
            if len(run) >= len(target):
                break
    return False


def _similar(a: str, b: str) -> float:
    if _word_match(a, b) or _word_match(b, a):
        return 0.95
    return difflib.SequenceMatcher(None, "".join(_tokens(a)), "".join(_tokens(b))).ratio()


def cmd_review_stations(conn: Connection, csv_path: Path) -> int:
    """DRY RUN (change plan 2026-11-12 Phase 1 step 4, DEC-37): distinct missing (state, station)
    pairs of an exceptions CSV, each with the closest existing station as a suggestion.

    Writes party_station_review.csv for the business to fill in the Decision column
    (ADD / MAP:<existing station> / STATE:<state> / SKIP). Reads only; nothing is written to the DB.
    """
    states, exact, _alias = _load_masters(conn)
    stations_by_state: dict[str, list[str]] = defaultdict(list)
    station_states: dict[str, list[str]] = defaultdict(list)
    state_name = {sid: name for sid, name in states.values()}
    for state_id, by_name in exact.items():
        for _st_id, st_name in by_name.values():
            stations_by_state[state_id].append(st_name)
            station_states[_norm(st_name)].append(state_name.get(state_id, "?"))

    pairs: Counter[tuple[str, str]] = Counter()
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            pairs[(_clean(row["State"]), _clean(row["Station"]))] += 1

    out: list[list[object]] = []
    for (state_raw, station_raw), n in sorted(pairs.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        state = states.get(_norm(state_raw))
        if state is None:
            elsewhere = station_states.get(_norm(station_raw), [])
            hint = f"{elsewhere[0]} / {station_raw.title()}" if len(elsewhere) == 1 else ""
            out.append([state_raw, station_raw, n, "", "REVIEW_STATE", hint, "", ""])
            continue
        state_id, resolved = state
        scored = sorted(
            ((_similar(station_raw, c), c) for c in stations_by_state.get(state_id, [])),
            reverse=True,
        )
        strong = [c for s, c in scored if s >= 0.95]
        if len(strong) > 1:
            # Several whole-word matches (Kanpur Dehat / Kanpur Nagar): never pick one.
            out.append(
                [
                    state_raw,
                    station_raw,
                    n,
                    resolved,
                    "MAP_AMBIGUOUS",
                    " | ".join(sorted(strong)),
                    "0.95",
                    "",
                ]
            )
            continue
        score, best = scored[0] if scored else (0.0, "")
        action = "MAP" if score >= 0.95 else ("MAP?" if score >= 0.85 else "ADD")
        out.append(
            [
                state_raw,
                station_raw,
                n,
                resolved,
                action,
                best if score >= 0.6 else "",
                f"{score:.2f}" if score >= 0.6 else "",
                "",
            ]
        )

    with REVIEW_FILE.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "State",
                "Station",
                "Rows",
                "Resolved State",
                "Suggested Action",
                "Closest Existing Station",
                "Similarity",
                "Decision",
            ]
        )
        writer.writerows(out)

    by_action = Counter(str(r[4]) for r in out)
    rows_by_action: Counter[str] = Counter()
    for r in out:
        rows_by_action[str(r[4])] += int(str(r[2]))
    print("=== Party exceptions — station review (DRY RUN, nothing written to the DB) ===")
    print(f"exception rows: {sum(pairs.values())}   distinct (state, station) pairs: {len(out)}")
    for action in ("ADD", "MAP", "MAP?", "MAP_AMBIGUOUS", "REVIEW_STATE"):
        print(f"  {action:<13} pairs={by_action[action]:<4} party rows={rows_by_action[action]}")
    print(f"review file: {REVIEW_FILE}")
    return 0


STATIONS_SEED_FILE = REPO_ROOT / "supabase" / "seed_stations.sql"


def _read_review(review_path: Path) -> list[dict[str, str]]:
    with review_path.open(encoding="utf-8-sig", newline="") as f:
        rows = [{k: _clean(v or "") for k, v in r.items()} for r in csv.DictReader(f)]
    if rows and "Decision" not in rows[0]:
        raise SystemExit(f"{review_path.name} has no Decision column")
    return rows


def _station_name(raw: str) -> str:
    """Display name for a new station: 'DEHRI ON SONE' -> 'Dehri On Sone'."""
    if not (raw.isupper() or raw.islower()):
        return raw  # already mixed case: keep as written
    return re.sub(r"[A-Za-z]+", lambda m: m.group(0).capitalize(), raw)


def cmd_station_review_seed(conn: Connection, review_path: Path, *, apply: bool) -> int:
    """Change plan 2026-11-12 Phase 1 step 4 (DEC-37): stations to ADD from a reviewed
    party_station_review.csv -> supabase/seed_stations.sql (generated; loaded before
    seed_parties.sql). Dry run by default; --apply also loads the seed into the DB.

    Decision column: ADD | ADD:<Station Name> | MAP:<existing station> | SKIP / blank.
    """
    states, exact, _alias = _load_masters(conn)
    add: dict[tuple[str, str], str] = {}  # (state name, NORM station) -> station name
    new: set[tuple[str, str]] = set()  # (state name, station name) not in the DB yet
    counts: Counter[str] = Counter()
    errors: list[str] = []
    for row in _read_review(review_path):
        decision = row["Decision"]
        kind = decision.split(":", 1)[0].strip().upper() or "SKIP"
        counts[kind] += 1
        if kind != "ADD":
            if kind not in ("MAP", "SKIP"):
                errors.append(f"{row['State']} / {row['Station']}: unknown decision '{decision}'")
            continue
        state = states.get(_norm(row["State"]))
        if state is None:
            errors.append(f"{row['State']} / {row['Station']}: state not in master")
            continue
        name = (
            decision.split(":", 1)[1].strip() if ":" in decision else _station_name(row["Station"])
        )
        # Every ADD station goes into the seed (so `supabase db reset` rebuilds it), including
        # ones already loaded by an earlier --apply; only the truly new ones are listed below.
        add.setdefault((state[1], _norm(name)), name)
        if _norm(name) not in exact[state[0]]:
            new.add((state[1], name))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1

    stations = sorted((s, n) for (s, _k), n in add.items())
    mode = "APPLIED" if apply else "DRY RUN (nothing written to the DB; re-run with --apply)"
    print(f"=== Station review -> seed_stations.sql — {mode} ===")
    print("decisions: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print(f"stations in seed: {len(stations)}   not yet in the DB: {len(new)}")
    for state_name, name in sorted(new):
        print(f"    + {state_name} / {name}")
    if not apply:
        return 0

    existing = ""
    if STATIONS_SEED_FILE.exists():
        # Keep stations added by earlier reviews: the seed is cumulative.
        existing = STATIONS_SEED_FILE.read_text(encoding="utf-8")
    prior = re.findall(r"^  \('((?:[^']|'')*)', '((?:[^']|'')*)'\)", existing, flags=re.M)
    merged = sorted(
        {(s.replace("''", "'"), n.replace("''", "'")) for s, n in prior} | set(stations)
    )
    if not merged:
        print("No stations to seed; seed not written.", file=sys.stderr)
        return 1
    values = ",\n".join(f"  ({_sql_literal(s)}, {_sql_literal(n)})" for s, n in merged)
    insert = f"insert into _seed_stations (state, station) values\n{values};\n"
    # Written to a file and loaded as-is; every value goes through _sql_literal.
    sql = f"""-- Stations added for the party import ({len(merged)} rows).
-- Change plan 2026-11-12 Phase 1, DEC-37.
-- GENERATED by backend/scripts/import_parties.py station-review-seed from the Decision column of
-- party_station_review.csv. Do not edit by hand: change the review file and re-run.
--
-- Loaded after seed.sql and BEFORE seed_parties.sql by `supabase db reset` (config.toml [db.seed]).
-- Idempotent (ON CONFLICT (state_id, name) DO NOTHING); a missing state aborts the load.

drop table if exists pg_temp._seed_stations;
create temporary table _seed_stations (state text, station text);

{insert}
do $$
declare
  missing text;
begin
  select string_agg(distinct v.state, ', ')
    into missing
    from _seed_stations v
    left join public.states s on s.name = v.state
   where s.id is null;
  if missing is not null then
    raise exception 'seed_stations: states not in masters: %', missing;
  end if;
end
$$;

insert into public.stations (state_id, name)
select s.id, v.station
  from _seed_stations v
  join public.states s on s.name = v.state
on conflict (state_id, name) do nothing;

drop table pg_temp._seed_stations;
"""  # noqa: S608
    STATIONS_SEED_FILE.write_text(sql, encoding="utf-8", newline="\n")
    # Raw driver cursor without parameters: the seed's RAISE '%' must not be read as a placeholder.
    cur = conn.connection.cursor()
    try:
        cur.execute(sql)
    finally:
        cur.close()
    print(f"wrote {len(merged)} stations to {STATIONS_SEED_FILE} and loaded it")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--db-url",
        default=os.environ.get("RMS_IMPORT_DATABASE_URL", LOCAL_SUPERUSER_URL),
        help="SQLAlchemy URL (default: local Supabase superuser)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import", help="insert parties from a State,Station,Client Name CSV")
    imp.add_argument("csv_path", type=Path)
    imp.add_argument(
        "--station-review",
        type=Path,
        help="apply MAP:<station> decisions of a reviewed party_station_review.csv",
    )
    seed = sub.add_parser(
        "station-review-seed",
        help="stations marked ADD in a reviewed file -> supabase/seed_stations.sql"
        " (dry run by default)",
    )
    seed.add_argument("review_path", type=Path)
    seed.add_argument("--apply", action="store_true", help="write the seed and load it into the DB")
    sub.add_parser("export-seed", help="write supabase/seed_parties.sql from the DB")
    rev = sub.add_parser(
        "review-stations",
        help="dry run: distinct missing (state, station) pairs of an exceptions CSV",
    )
    rev.add_argument("csv_path", type=Path)
    args = parser.parse_args()

    engine = create_engine(args.db_url)
    if args.command == "review-stations":
        with engine.connect() as conn:
            result = cmd_review_stations(conn, args.csv_path)
            conn.rollback()  # read-only
            return result
    if args.command == "station-review-seed":
        with engine.connect() as conn:
            result = cmd_station_review_seed(conn, args.review_path, apply=args.apply)
            if args.apply and result == 0:
                conn.commit()
            else:
                conn.rollback()
            return result
    with engine.begin() as conn:
        if args.command == "import":
            return cmd_import(conn, args.csv_path, args.station_review)
        return cmd_export_seed(conn)


if __name__ == "__main__":
    raise SystemExit(main())
