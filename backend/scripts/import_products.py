"""Product (item) master bulk import (CSV) and go-live seed export.

    uv run python scripts/import_products.py import ../items.csv              # dry run (default)
    uv run python scripts/import_products.py import ../items.csv --apply      # write to the DB
    uv run python scripts/import_products.py import ../items.csv --create-categories [--apply]
    uv run python scripts/import_products.py export-seed

`import` reads a CSV with the columns `Item Name` (or `Product Name`), `Category` and, optionally,
`Sub-Category` (change plan 2026-11-12 Phase 1, AMD-07, DEC-36), plus optional `UOM` / `HSN`.
The rules are shared with the Admin UI import (app/modules/masters/product_import.py):

* Category is matched by code or name. An unknown category is an exception unless
  --create-categories is given (new categories carry no hazard/battery/opening flags).
* Missing sub-categories are created under their category (code derived from the name).
* Existing products are matched by name (ignoring case and repeated spaces) and get their
  category / sub-category updated; unknown names are inserted with the next `ITM-` code.
* Rows that cannot be imported are written to `product_import_exceptions.csv` (repository root)
  with a reason, on a dry run as well as on --apply.

Without --apply nothing is written to the DB: the summary shows exactly what --apply would do.
--apply runs in one transaction; any error rolls everything back.

`export-seed` writes every product category used by an `ITM-` product, every sub-category and
every `ITM-` product to `supabase/seed_products.sql`, keyed by *codes*, so it applies to any
database built from the migrations and seed.sql (`supabase db reset` loads it via config.toml; at
go-live run it with psql). The seed is idempotent and fails loudly if a category is missing.

The database defaults to the local Supabase superuser; pass --db-url (or set
RMS_IMPORT_DATABASE_URL) for another database.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.modules.masters import repository as repo
from app.modules.masters.product_import import (
    CsvFormatError,
    ImportPlan,
    parse_csv,
    plan_import,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EXCEPTIONS_FILE = REPO_ROOT / "product_import_exceptions.csv"
SEED_FILE = REPO_ROOT / "supabase" / "seed_products.sql"
LOCAL_SUPERUSER_URL = "postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres"
CORE_CATEGORY_CODES = ("DMT", "PRISMATIC", "ENCLOSED_OVAL", "GENERAL")  # created by seed.sql


def _print_summary(plan: ImportPlan, *, applied: bool, codes: list[str]) -> None:
    mode = "APPLIED" if applied else "DRY RUN (nothing written; re-run with --apply)"
    print(f"=== Product import — {mode} ===")
    print(f"rows read:              {plan.rows_read}")
    print(f"new categories:         {len(plan.new_categories)}")
    for c in plan.new_categories:
        print(f"    + {c.code:<28} {c.name}   (no hazard/battery/opening flags — review)")
    print(f"new sub-categories:     {len(plan.new_subcategories)}")
    for s in plan.new_subcategories:
        print(f"    + {s.category_code} / {s.code:<28} {s.name}")
    print(f"new products:           {len(plan.new_products)}")
    for i, p in enumerate(plan.new_products):
        code = codes[i] if applied else "(new)"
        print(f"    + {code:<10} {p.name}  ->  {p.category_code} / {p.subcategory_code or '-'}")
    moved = [u for u in plan.updates if u.category_changed]
    print(f"updated products:       {len(plan.updates)}  (category changes: {len(moved)})")
    for u in plan.updates:
        print(
            f"    ~ {u.product_code:<10} {u.name}  :  "
            f"{u.from_category} / {u.from_subcategory or '-'}"
            f"  ->  {u.to_category} / {u.to_subcategory or '-'}"
        )
    print(f"unchanged products:     {plan.unchanged}")
    print(f"duplicates in file:     {plan.duplicates_in_file}")
    print(f"exceptions:             {len(plan.exceptions)}")
    reasons = Counter(re.sub(r"'[^']*'", "'…'", e.reason) for e in plan.exceptions)
    for reason, n in reasons.most_common():
        print(f"    ! {n:>4} x {reason}")


def cmd_import(conn: Connection, csv_path: Path, *, apply: bool, create_categories: bool) -> int:
    try:
        rows = parse_csv(csv_path.read_text(encoding="utf-8-sig"))
    except CsvFormatError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if apply:
        repo.lock_product_import(conn)
    plan = plan_import(rows, repo.load_snapshot(conn), create_categories=create_categories)
    codes = repo.apply_import(conn, plan) if apply else []

    with EXCEPTIONS_FILE.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["CSV Row", "Item Name", "Category", "Sub-Category", "Reason"])
        writer.writerows(
            [e.row_no, e.item_name, e.category, e.sub_category, e.reason] for e in plan.exceptions
        )

    _print_summary(plan, applied=apply, codes=codes)
    print(f"exceptions file: {EXCEPTIONS_FILE}")
    if apply:
        print("Run `export-seed` to refresh supabase/seed_products.sql.")
    return 0


def _sql_literal(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return "'" + str(value).replace("'", "''") + "'"


def _values(rows: list[tuple[object, ...]]) -> str:
    return ",\n".join(f"  ({', '.join(_sql_literal(v) for v in row)})" for row in rows)


def cmd_export_seed(conn: Connection) -> int:
    products = [
        tuple(r)
        for r in conn.execute(
            text(
                """
                select p.code, p.name, c.code, s.code, p.uom, p.hsn_code
                  from public.products p
                  join public.product_categories c on c.id = p.category_id
                  left join public.product_subcategories s on s.id = p.subcategory_id
                 where p.code ~ ('^' || :p || '[0-9]+$')
                 order by p.code
                """
            ),
            {"p": repo.PRODUCT_CODE_PREFIX},
        )
    ]
    if not products:
        print("No ITM- products in the database; seed not written.", file=sys.stderr)
        return 1
    # Categories created outside seed.sql (e.g. by --create-categories), so the seed can make them.
    categories = [
        tuple(r)
        for r in conn.execute(
            text(
                "select code, name from public.product_categories"
                " where not (code = any(:core)) order by code"
            ),
            {"core": list(CORE_CATEGORY_CODES)},
        )
    ]
    subcategories = [
        tuple(r)
        for r in conn.execute(
            text(
                """
                select c.code, s.code, s.name, s.is_active
                  from public.product_subcategories s
                  join public.product_categories c on c.id = s.category_id
                 order by c.code, s.code
                """
            )
        )
    ]

    cat_block = (
        f"""insert into public.product_categories (code, name) values
{_values(categories)}
on conflict (code) do nothing;
"""  # noqa: S608 - written to a file; values via _sql_literal
        if categories
        else "-- (no product categories beyond seed.sql)\n"
    )
    sub_values = _values(subcategories) if subcategories else None
    sub_block = (
        f"""insert into _seed_subcategories (category, code, name, is_active) values
{sub_values};
"""  # noqa: S608 - written to a file; values via _sql_literal
        if sub_values
        else ""
    )
    # Written to a file, not executed here; every value goes through _sql_literal.
    SEED_FILE.write_text(
        f"""-- Product (item) master: bulk-imported products ({len(products)} rows).
-- Sub-categories: {len(subcategories)} rows. Extra categories: {len(categories)} rows.
-- GENERATED by backend/scripts/import_products.py export-seed. Do not edit by hand:
-- import into the DB, then re-export.
--
-- Loaded after seed.sql by `supabase db reset` (config.toml [db.seed]). At go-live:
--   psql "$DB_URL" -v ON_ERROR_STOP=1 -1 -f supabase/seed_products.sql
-- Idempotent: ON CONFLICT ... DO NOTHING never overwrites admin edits to an existing row; an
-- existing product without a sub-category only gets the seeded one when its category matches.
-- Categories are resolved by code; a missing category aborts the load (no silent drops).
-- AMD-07: products.subcategory_id must belong to the product's category (DB-enforced).

{cat_block}
drop table if exists pg_temp._seed_subcategories;
create temporary table _seed_subcategories (
  category text, code text, name text, is_active boolean
);
{sub_block}
drop table if exists pg_temp._seed_products;
create temporary table _seed_products (
  code text, name text, category text, subcategory text, uom text, hsn_code text
);

insert into _seed_products (code, name, category, subcategory, uom, hsn_code) values
{_values(products)};

do $$
declare
  missing text;
begin
  select string_agg(distinct v.category, ', ')
    into missing
    from (select category from _seed_products union select category from _seed_subcategories) v
    left join public.product_categories c on c.code = v.category
   where c.id is null;
  if missing is not null then
    raise exception 'seed_products: product categories not in masters: %', missing;
  end if;
end
$$;

insert into public.product_subcategories (category_id, code, name, is_active)
select c.id, v.code, v.name, v.is_active
  from _seed_subcategories v
  join public.product_categories c on c.code = v.category
on conflict (category_id, code) do nothing;

insert into public.products (code, name, category_id, subcategory_id, uom, hsn_code)
select v.code, v.name, c.id, s.id, v.uom, v.hsn_code
  from _seed_products v
  join public.product_categories c on c.code = v.category
  left join public.product_subcategories s on s.category_id = c.id and s.code = v.subcategory
on conflict (code) do nothing;

update public.products p
   set subcategory_id = s.id
  from _seed_products v
  join public.product_categories c on c.code = v.category
  join public.product_subcategories s on s.category_id = c.id and s.code = v.subcategory
 where p.code = v.code and p.subcategory_id is null and p.category_id = c.id;

drop table pg_temp._seed_products;
drop table pg_temp._seed_subcategories;
""",  # noqa: S608
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"wrote {len(products)} products, {len(subcategories)} sub-categories, "
        f"{len(categories)} extra categories to {SEED_FILE}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--db-url",
        default=os.environ.get("RMS_IMPORT_DATABASE_URL", LOCAL_SUPERUSER_URL),
        help="SQLAlchemy URL (default: local Supabase superuser)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import", help="dry-run (default) or apply a product CSV")
    imp.add_argument("csv_path", type=Path)
    imp.add_argument("--apply", action="store_true", help="write to the DB (default: dry run)")
    imp.add_argument(
        "--create-categories",
        action="store_true",
        help="create categories that do not exist yet (no behaviour flags)",
    )
    sub.add_parser("export-seed", help="write supabase/seed_products.sql from the DB")
    args = parser.parse_args()

    engine = create_engine(args.db_url)
    with engine.connect() as conn:
        if args.command == "import":
            result = cmd_import(
                conn, args.csv_path, apply=args.apply, create_categories=args.create_categories
            )
            # One transaction: committed only for --apply with success; a dry run never writes.
            if args.apply and result == 0:
                conn.commit()
            else:
                conn.rollback()
            return result
        result = cmd_export_seed(conn)
        conn.rollback()  # export only reads
        return result


if __name__ == "__main__":
    raise SystemExit(main())
