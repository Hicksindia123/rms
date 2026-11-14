"""Helpers shared by the P2-08 Phase 2 gate suites (plain functions; fixtures are in conftest)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from httpx import AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.orm import Session, sessionmaker

from tests.integration.conftest import as_admin, fetch_all
from tests.integration.test_gate_inward import Masters, _auth
from tests.integration.test_itemization import add_line, categorize, key
from tests.integration.test_unboxing import (
    INVOICE,
    Actors,
    FakeStorage,
    classify,
    complete,
    started_gs,
    upload,
    upload_videos,
)


@dataclass
class Admin:
    id: uuid.UUID
    token: str


@dataclass
class Products:
    dmt: str
    prismatic: str
    eo: str


# --- helpers -------------------------------------------------------------------------------------
def guard_of(res: Any) -> str | None:
    """The guard code of an error envelope, or None (the response must be an error)."""
    assert res.status_code >= 400, (
        f"expected the guard to reject, got {res.status_code}: {res.text}"
    )
    return str(res.json()["error"]["code"])


async def itemizing_gs(client: AsyncClient, storage: FakeStorage, a: Actors, m: Masters) -> str:
    gs_id = await started_gs(client, a, m)
    await upload_videos(client, storage, a.aman, gs_id)
    photo = await upload(client, storage, a.aman, gs_id, "DOC_PHOTO", "image/jpeg")
    assert (await classify(client, a.aman, gs_id, photo["id"], INVOICE)).status_code == 201
    assert (await complete(client, a.aman, gs_id)).status_code == 200
    return gs_id


async def gs_at(
    client: AsyncClient,
    storage: FakeStorage,
    a: Actors,
    m: Masters,
    lines: list[tuple[str, int, int]],
    category: str = "RO",
) -> tuple[str, list[str]]:
    gs_id = await itemizing_gs(client, storage, a, m)
    item_ids = []
    for product, doc, recv in lines:
        res = await add_line(client, a.aman, gs_id, product, doc, recv)
        assert res.status_code == 201, res.text
        item_ids.append(str(res.json()["id"]))
    res = await categorize(client, a.aman, gs_id, category)
    assert res.status_code == 200, res.text
    return gs_id, item_ids


async def grade(
    client: AsyncClient,
    token: str,
    item_id: str,
    allocations: dict[str, int],
    *,
    packaging: int,
    container: int = 0,
    full_opening: bool = True,
) -> Any:
    return await client.put(
        f"/api/v1/gs-items/{item_id}/inspection",
        json={
            "full_opening_confirmed": full_opening,
            "allocations": [{"condition_code": c, "qty": q} for c, q in allocations.items()],
            "extraction": {
                "primary_type": "PACKAGING_EXTRACTED" if packaging else "CONTAINER_EXTRACTED",
                "packaging_qty": packaging,
                "container_qty": container,
            },
        },
        headers=_auth(token),
    )


async def finalise(client: AsyncClient, token: str, item_id: str) -> Any:
    return await client.post(
        f"/api/v1/gs-items/{item_id}/inspection/finalise", headers=_auth(token, key())
    )


def gs_status(conn: Connection, gs_id: str) -> str:
    return str(
        as_admin(conn)
        .execute(text("select status from public.goods_slips where id = :g"), {"g": gs_id})
        .scalar_one()
    )


def location_id(conn: Connection, code: str) -> uuid.UUID:
    return uuid.UUID(
        str(
            as_admin(conn)
            .execute(text("select id from public.inventory_locations where code = :c"), {"c": code})
            .scalar_one()
        )
    )


def lot_for(conn: Connection, item_id: str, condition_class: str) -> dict[str, Any]:
    rows = fetch_all(
        conn,
        """select l.id, l.condition_class, l.is_pending, il.code as location, b.qty
             from public.stock_lots l
             join public.stock_balances b on b.lot_id = l.id and b.qty > 0
             join public.inventory_locations il on il.id = b.location_id
            where l.gs_item_id = :i and l.condition_class = :c""",
        i=item_id,
        c=condition_class,
    )
    assert len(rows) == 1, rows
    return rows[0]


def functional_qty(conn: Connection, gs_id: str) -> int:
    return int(
        as_admin(conn)
        .execute(
            text(
                """select coalesce(sum(b.qty), 0) from public.stock_balances b
                     join public.stock_lots l on l.id = b.lot_id
                     join public.inventory_locations il on il.id = b.location_id
                    where l.gs_id = :g and il.location_class = 'FUNCTIONAL'"""
            ),
            {"g": gs_id},
        )
        .scalar_one()
    )


def move_as_super_admin(
    factory: sessionmaker[Session],
    admin_id: uuid.UUID,
    *,
    lot: Any,
    src: uuid.UUID | None,
    dst: uuid.UUID | None,
    qty: int,
) -> None:
    """Call the locked ledger function exactly as the API does (role rms_api) as the Super Admin."""
    with factory() as s:
        s.execute(text("select set_config('app.user_id', :u, true)"), {"u": str(admin_id)})
        s.execute(
            text(
                """select rms_private.rms_move_stock(
                     p_lot => :lot, p_from => :src, p_to => :dst, p_qty => :qty,
                     p_type => 'TRANSFER_OUT', p_ref_type => 'guard_regression', p_ref_id => null,
                     p_idem_key => :k, p_actor => :actor, p_reason => 'P2-08 bypass attempt')"""
            ),
            {"lot": lot, "src": src, "dst": dst, "qty": qty, "k": key(), "actor": admin_id},
        )
        s.commit()


def db_attempt(factory: sessionmaker[Session], admin_id: uuid.UUID, sql: str, **p: Any) -> None:
    """Run a statement as rms_api with the Super Admin as the audit actor; it must be rejected."""
    with factory() as s:
        s.execute(text("select set_config('app.user_id', :u, true)"), {"u": str(admin_id)})
        s.execute(text(sql), p)
        s.commit()
