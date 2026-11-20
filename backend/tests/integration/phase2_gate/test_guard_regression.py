"""P2-08 · Phase 2 gate: system-guard regression suite (master plan §4.2, CLAUDE.md rule c).

One test per guard G-01..G-08 and G-16..G-18. Every test attempts the bypass with a VALID token,
always including a Super Admin, through the public API. Where Phase 2 has no API that can reach the
guard (there is no endpoint that moves stock between arbitrary locations yet), the attempt is made
against the locked database function / table under the API's own `rms_api` role with the Super
Admin as the acting user. Every attempt must fail and leave the data unchanged.
"""

from __future__ import annotations

import re
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import SystemGuardViolation
from app.modules.custody import service as custody_service
from tests.integration.conftest import fetch_all
from tests.integration.phase2_gate.helpers import (
    Admin,
    Products,
    db_attempt,
    finalise,
    functional_qty,
    grade,
    gs_at,
    gs_status,
    guard_of,
    itemizing_gs,
    location_id,
    lot_for,
    move_as_super_admin,
)
from tests.integration.test_gate_inward import GS_NO, Masters, _auth, _create, _values
from tests.integration.test_itemization import add_line, categorize, key
from tests.integration.test_unboxing import (
    Actors,
    FakeStorage,
    complete,
    started_gs,
    upload,
    upload_videos,
)

pytestmark = pytest.mark.asyncio


# --- G-01 ----------------------------------------------------------------------------------------
async def test_g01_no_record_without_a_generated_gs_number(
    client: AsyncClient,
    db_conn: Connection,
    actors: Actors,
    admin: Admin,
    masters: Masters,
    products: Products,
) -> None:
    """G-01: items need an existing GS; GS numbers are generated server-side and immutable."""
    ghost = str(uuid.uuid4())
    for token in (admin.token, actors.aman):
        res = await add_line(client, token, ghost, products.dmt, 1, 1)
        assert res.status_code in (404, 409, 422), res.text
    assert not fetch_all(db_conn, "select 1 from public.gs_items where gs_id = :g", g=ghost)

    # A client-supplied GS number is never used: the server generates it (BR-01, DEC-01).
    res = await _create(client, admin.token, masters, _values(gs_no="FORGED/0001"), gs_no="X/1")
    if res.status_code == 201:
        gs = res.json()["goods_slip"]
        assert GS_NO.fullmatch(gs["gs_no"]), gs["gs_no"]
        gs_id = gs["id"]
    else:
        assert res.status_code == 422, res.text
        res = await _create(client, admin.token, masters, _values())
        assert res.status_code == 201, res.text
        gs_id = res.json()["goods_slip"]["id"]
    original = res.json()["goods_slip"]["gs_no"]

    # Super Admin edit of the number through the gate edit endpoint does not change it.
    res = await client.patch(
        f"/api/v1/gs/{gs_id}/gate",
        json={"values": _values(gs_no="FORGED/0002"), "reason": "bypass attempt", "gs_no": "F/2"},
        headers=_auth(admin.token),
    )
    assert fetch_all(db_conn, "select gs_no from public.goods_slips where id = :g", g=gs_id) == [
        {"gs_no": original}
    ], res.text


# --- G-02 ----------------------------------------------------------------------------------------
async def test_g02_unboxing_cannot_complete_without_evidence(
    client: AsyncClient,
    db_conn: Connection,
    storage: FakeStorage,
    actors: Actors,
    admin: Admin,
    masters: Masters,
    session_factory: sessionmaker[Session],
) -> None:
    gs_id = await started_gs(client, actors, masters)
    for token in (admin.token, actors.aman):
        assert guard_of(await complete(client, token, gs_id)) == "G-02"
    # DEC-63: G-02 = a confirmed video for every carton. Cartons 1 and 2 of 3 are not enough,
    # also not for a Super Admin, in the service and in the DB.
    for box in (1, 2):
        await upload(client, storage, actors.aman, gs_id, "UNBOXING_VIDEO", "video/mp4", box_no=box)
    assert guard_of(await complete(client, admin.token, gs_id)) == "G-02"
    with pytest.raises(DBAPIError, match="G-02"):
        db_attempt(
            session_factory,
            admin.id,
            "update public.goods_slips set status = 'ITEMIZATION' where id = :g",
            g=gs_id,
        )
    assert gs_status(db_conn, gs_id) == "UNBOXING"
    await upload_videos(client, storage, actors.aman, gs_id)
    res = await complete(client, actors.aman, gs_id)
    assert res.status_code == 200, res.text  # no document photo, no exception (DEC-63)


# --- G-03 ----------------------------------------------------------------------------------------
async def test_g03_csr_cannot_advance_without_rm_decision(
    client: AsyncClient,
    db_conn: Connection,
    storage: FakeStorage,
    actors: Actors,
    admin: Admin,
    masters: Masters,
    products: Products,
    session_factory: sessionmaker[Session],
) -> None:
    gs_id, items = await gs_at(
        client, storage, actors, masters, [(products.dmt, 5, 5)], category="CSR"
    )
    assert gs_status(db_conn, gs_id) == "CSR_APPROVAL_PENDING"

    # The verifier (no approve permission) cannot decide.
    res = await client.post(
        f"/api/v1/gs/{gs_id}/csr-decision",
        json={"decision": "CSR_APPROVED", "remarks": "self-approval"},
        headers=_auth(actors.aman, key()),
    )
    assert res.status_code == 403, res.text
    # Nobody - Super Admin included - can skip the decision by re-categorising, inspecting,
    # or recording RM actions.
    assert (await categorize(client, admin.token, gs_id, "RO")).status_code in (409, 422)
    assert (
        await grade(client, admin.token, items[0], {"DMT_OK_PACKED": 5}, packaging=5)
    ).status_code in (403, 409, 422)
    res = await client.post(
        f"/api/v1/gs/{gs_id}/inspection/finalise-all", headers=_auth(admin.token, key())
    )
    assert res.status_code in (403, 409, 422), res.text
    for status in ("INSPECTION", "IN_PROCESS", "RM_REVIEW"):
        with pytest.raises(DBAPIError, match="G-03"):
            db_attempt(
                session_factory,
                admin.id,
                "update public.goods_slips set status = :s where id = :g",
                s=status,
                g=gs_id,
            )
    assert gs_status(db_conn, gs_id) == "CSR_APPROVAL_PENDING"


# --- G-04 ----------------------------------------------------------------------------------------
async def test_g04_not_allowed_stock_never_reaches_functional(
    client: AsyncClient,
    db_conn: Connection,
    storage: FakeStorage,
    actors: Actors,
    admin: Admin,
    masters: Masters,
    products: Products,
    session_factory: sessionmaker[Session],
) -> None:
    gs_id, items = await gs_at(client, storage, actors, masters, [(products.dmt, 10, 10)])
    res = await grade(
        client,
        admin.token,
        items[0],
        {"DMT_OK_PACKED": 8, "DMT_OTHER_BRANDS": 2},
        packaging=10,
    )
    assert res.status_code == 200, res.text
    assert (await finalise(client, admin.token, items[0])).status_code == 200

    rejected = lot_for(db_conn, items[0], "NOT_ALLOWED")
    assert rejected["location"] == "REJECTED_HOLD"
    assert functional_qty(db_conn, gs_id) == 0
    with pytest.raises(DBAPIError, match="G-04"):
        move_as_super_admin(
            session_factory,
            admin.id,
            lot=rejected["id"],
            src=location_id(db_conn, "REJECTED_HOLD"),
            dst=location_id(db_conn, "INTERMEDIATE_STORE"),
            qty=2,
        )
    assert functional_qty(db_conn, gs_id) == 0
    assert lot_for(db_conn, items[0], "NOT_ALLOWED")["qty"] == 2


# --- G-05 ----------------------------------------------------------------------------------------
async def test_g05_mercury_hazard_only_in_quarantine(
    client: AsyncClient,
    db_conn: Connection,
    storage: FakeStorage,
    actors: Actors,
    admin: Admin,
    masters: Masters,
    products: Products,
    session_factory: sessionmaker[Session],
) -> None:
    _gs_id, items = await gs_at(client, storage, actors, masters, [(products.prismatic, 5, 5)])
    res = await grade(
        client, admin.token, items[0], {"PRS_OK": 3, "PRS_BROKEN_WITH_HG": 2}, packaging=5
    )
    assert res.status_code == 200, res.text
    assert (await finalise(client, admin.token, items[0])).status_code == 200
    hazard = lot_for(db_conn, items[0], "HAZARD")
    assert hazard["location"] == "HAZARD_QUARANTINE"

    for target in ("REJECTED_HOLD", "INTERMEDIATE_STORE", "TRANSIT"):
        with pytest.raises(DBAPIError, match=r"G-0[45]"):
            move_as_super_admin(
                session_factory,
                admin.id,
                lot=hazard["id"],
                src=location_id(db_conn, "HAZARD_QUARANTINE"),
                dst=location_id(db_conn, target),
                qty=1,
            )
    # Configuration cannot downgrade the hazard condition either (Admin Panel, Super Admin).
    prs = (
        await client.get(
            "/api/v1/config/option-sets/PRISMATIC_CONDITION", headers=_auth(admin.token)
        )
    ).json()
    item = next(i for i in prs["items"] if i["code"] == "PRS_BROKEN_WITH_HG")
    res = await client.put(
        f"/api/v1/config/option-sets/{prs['id']}/items/{item['id']}",
        json={"allowed_status": "YES", "reason": "P2-08 bypass attempt"},
        headers=_auth(admin.token),
    )
    assert guard_of(res) == "G-05"
    assert lot_for(db_conn, items[0], "HAZARD")["location"] == "HAZARD_QUARANTINE"


# --- G-06 ----------------------------------------------------------------------------------------
async def test_g06_enclosed_oval_needs_full_opening(
    client: AsyncClient,
    db_conn: Connection,
    storage: FakeStorage,
    actors: Actors,
    admin: Admin,
    masters: Masters,
    products: Products,
    session_factory: sessionmaker[Session],
) -> None:
    gs_id, items = await gs_at(client, storage, actors, masters, [(products.eo, 4, 4)])
    for token in (admin.token, actors.aman):
        res = await grade(client, token, items[0], {"EO_OK": 4}, packaging=4, full_opening=False)
        assert guard_of(res) == "G-06"
    assert (await finalise(client, admin.token, items[0])).status_code in (409, 422)

    # Direct DB write of an EO allocation on an unopened inspection.
    insp_id = uuid.uuid4()
    with pytest.raises(DBAPIError, match="G-06"):
        db_attempt(
            session_factory,
            admin.id,
            """with i as (insert into public.inspections (id, gs_item_id, full_opening_confirmed)
                          values (:i, :item, false) returning id)
               insert into public.inspection_allocations (inspection_id, condition_code, qty)
               select id, 'EO_OK', 4 from i""",
            i=insp_id,
            item=items[0],
        )
    assert gs_status(db_conn, gs_id) == "INSPECTION"


# --- G-07 ----------------------------------------------------------------------------------------
async def test_g07_finalise_requires_reconciled_quantities(
    client: AsyncClient,
    db_conn: Connection,
    storage: FakeStorage,
    actors: Actors,
    admin: Admin,
    masters: Masters,
    products: Products,
    session_factory: sessionmaker[Session],
) -> None:
    gs_id, items = await gs_at(client, storage, actors, masters, [(products.dmt, 10, 10)])
    # Σ conditions (8) ≠ received (10)
    assert (
        await grade(client, admin.token, items[0], {"DMT_OK_PACKED": 8}, packaging=10)
    ).status_code == 200
    assert guard_of(await finalise(client, admin.token, items[0])) == "G-07"
    res = await client.post(
        f"/api/v1/gs/{gs_id}/inspection/finalise-all", headers=_auth(admin.token, key())
    )
    assert guard_of(res) == "G-07"
    # Σ conditions OK, extraction (7) ≠ received (10)
    res = await grade(
        client, admin.token, items[0], {"DMT_OK_PACKED": 10}, packaging=0, container=7
    )
    assert res.status_code == 200, res.text
    assert guard_of(await finalise(client, admin.token, items[0])) == "G-07"
    with pytest.raises(DBAPIError, match="G-07"):
        db_attempt(
            session_factory,
            admin.id,
            "update public.goods_slips set status = 'RM_REVIEW' where id = :g",
            g=gs_id,
        )
    assert gs_status(db_conn, gs_id) == "INSPECTION"


# --- G-08 ----------------------------------------------------------------------------------------
async def test_g08_pending_bp_is_held_and_blocks_the_gs(
    client: AsyncClient,
    db_conn: Connection,
    storage: FakeStorage,
    actors: Actors,
    admin: Admin,
    masters: Masters,
    products: Products,
    session_factory: sessionmaker[Session],
) -> None:
    gs_id, items = await gs_at(client, storage, actors, masters, [(products.dmt, 10, 10)])
    assert (
        await grade(client, actors.aman, items[0], {"DMT_OK_PACKED": 10}, packaging=10)
    ).status_code == 200
    assert (await finalise(client, actors.aman, items[0])).status_code == 200
    res = await client.put(
        f"/api/v1/gs/{gs_id}/rm-actions",
        json={
            "lines": [
                {
                    "gs_item_id": items[0],
                    "actions": [
                        {"action_code": "SEND_NEW", "qty": 8},
                        {"action_code": "PENDING_BP", "qty": 2},
                    ],
                }
            ],
            "pendency_details": {
                items[0]: {"reason": "With Repair Team", "sent_to": "Repair Team"}
            },
        },
        headers=_auth(admin.token),
    )
    assert res.status_code == 200, res.text
    pending = fetch_all(
        db_conn,
        """select l.id from public.stock_lots l where l.gs_item_id = :i and l.is_pending""",
        i=items[0],
    )[0]

    # (1) Pending pieces cannot move to transit / functional, nor be put on a transfer.
    with pytest.raises(DBAPIError, match="G-08"):
        move_as_super_admin(
            session_factory,
            admin.id,
            lot=pending["id"],
            src=location_id(db_conn, "PENDING_HOLD"),
            dst=location_id(db_conn, "TRANSIT"),
            qty=2,
        )
    with session_factory() as s, pytest.raises(SystemGuardViolation) as exc:
        custody_service.propose_transfer(
            s,
            gs_id=uuid.UUID(gs_id),
            from_location_code="PENDING_HOLD",
            to_location_code="INTERMEDIATE_STORE",
            lines=[custody_service.ProposedLine(lot_id=uuid.UUID(str(pending["id"])), qty=2)],
            purpose_code=None,
            with_packaging=False,
            notes=None,
            by=admin.id,
        )
    assert exc.value.guard == "G-08"
    with pytest.raises(DBAPIError, match="G-08"):
        db_attempt(
            session_factory,
            admin.id,
            """with t as (insert into public.custody_transfers
                            (transfer_no, gs_id, from_location_id, to_location_id, mode_code,
                             status, stock_moved, initiated_by)
                          values (:no, :g, :src, :dst, 'PHYSICAL_AND_DIGITAL', 'INITIATED', false,
                                  :by) returning id)
               insert into public.custody_transfer_lines (transfer_id, lot_id, qty_sent)
               select id, :lot, 2 from t""",
            no=f"TRF-G08-{uuid.uuid4().hex[:6]}",
            g=gs_id,
            src=location_id(db_conn, "PENDING_HOLD"),
            dst=location_id(db_conn, "INTERMEDIATE_STORE"),
            lot=pending["id"],
            by=admin.id,
        )

    # (2) DEC-12 toggle on (config, via the Admin API): the GS cannot leave RM_REVIEW at all.
    res = await client.put(
        "/api/v1/config/settings/pending_blocks_entire_gs",
        json={"value": True, "reason": "P2-08 guard regression"},
        headers=_auth(admin.token),
    )
    assert res.status_code == 200, res.text
    res = await client.post(f"/api/v1/gs/{gs_id}/rm-actions/finalise", headers=_auth(admin.token))
    assert guard_of(res) == "G-08"
    with pytest.raises(DBAPIError, match="G-08"):
        db_attempt(
            session_factory,
            admin.id,
            "update public.goods_slips set status = 'IN_PROCESS' where id = :g",
            g=gs_id,
        )
    assert gs_status(db_conn, gs_id) == "RM_REVIEW"

    # (3) Toggle off: handover may proceed (DEC-12), but no setting lifts the Stage-6 block.
    res = await client.put(
        "/api/v1/config/settings/pending_blocks_entire_gs",
        json={"value": False, "reason": "P2-08 guard regression"},
        headers=_auth(admin.token),
    )
    assert res.status_code == 200, res.text
    res = await client.post(f"/api/v1/gs/{gs_id}/rm-actions/finalise", headers=_auth(admin.token))
    assert res.status_code == 200, res.text
    for stage6 in ("COMMERCIAL_RESOLUTION", "AWAITING_NOTIFICATION", "CLOSED"):
        with pytest.raises(DBAPIError, match="G-08"):
            db_attempt(
                session_factory,
                admin.id,
                "update public.goods_slips set status = :s where id = :g",
                s=stage6,
                g=gs_id,
            )
    assert gs_status(db_conn, gs_id) == "IN_PROCESS"


# --- G-16 ----------------------------------------------------------------------------------------
async def test_g16_no_negative_stock_and_idempotent_commands(
    client: AsyncClient,
    db_conn: Connection,
    storage: FakeStorage,
    actors: Actors,
    admin: Admin,
    masters: Masters,
    products: Products,
    session_factory: sessionmaker[Session],
) -> None:
    gs_id = await itemizing_gs(client, storage, actors, masters)
    res = await add_line(client, actors.aman, gs_id, products.dmt, 6, 6)
    assert res.status_code == 201, res.text
    item_id = str(res.json()["id"])

    # A stock command without an Idempotency-Key is refused.
    res = await client.post(
        f"/api/v1/gs/{gs_id}/categorize", json={"category": "RO"}, headers=_auth(admin.token)
    )
    assert res.status_code in (400, 422), res.text
    # The same key twice returns the original result and inwards the stock once.
    idem = key()
    first = await categorize(client, admin.token, gs_id, "RO", idem)
    second = await categorize(client, admin.token, gs_id, "RO", idem)
    assert first.status_code == second.status_code == 200, second.text
    assert first.json() == second.json()
    # The same key with a different body is a conflict, not a second command.
    res = await client.post(
        f"/api/v1/gs/{gs_id}/categorize",
        json={"category": "CSR"},
        headers=_auth(admin.token, idem),
    )
    assert res.status_code in (409, 422), res.text
    lot = lot_for(db_conn, item_id, "AS_RECEIVED")
    assert (lot["location"], lot["qty"]) == ("INWARD_STAGING", 6)

    # Overdrawing the balance through the locked function fails, as Super Admin.
    with pytest.raises(DBAPIError, match="G-16"):
        move_as_super_admin(
            session_factory,
            admin.id,
            lot=lot["id"],
            src=location_id(db_conn, "INWARD_STAGING"),
            dst=location_id(db_conn, "REJECTED_HOLD"),
            qty=7,
        )
    # Writing the balance table directly is impossible (CHECK qty >= 0 / no write path).
    with pytest.raises(DBAPIError):
        db_attempt(
            session_factory,
            admin.id,
            "update public.stock_balances set qty = -1 where lot_id = :l",
            l=lot["id"],
        )
    assert lot_for(db_conn, item_id, "AS_RECEIVED")["qty"] == 6


# --- G-17 ----------------------------------------------------------------------------------------
async def test_g17_every_change_is_audited_and_the_audit_is_append_only(
    client: AsyncClient,
    db_conn: Connection,
    storage: FakeStorage,
    actors: Actors,
    admin: Admin,
    masters: Masters,
    products: Products,
    session_factory: sessionmaker[Session],
) -> None:
    res = await _create(client, admin.token, masters, _values())
    assert res.status_code == 201, res.text
    gs_id = res.json()["goods_slip"]["id"]
    rows = fetch_all(
        db_conn,
        """select table_name, action from public.audit_log
            where row_id = :g and actor_id = :a""",
        g=gs_id,
        a=admin.id,
    )
    assert {"table_name": "public.goods_slips", "action": "INSERT"} in rows

    # Option relabel by the Super Admin is a configuration change and is attributed to them.
    dmt = (
        await client.get("/api/v1/config/option-sets/DMT_CONDITION", headers=_auth(admin.token))
    ).json()
    item = next(i for i in dmt["items"] if i["code"] == "DMT_DIRTY")
    res = await client.put(
        f"/api/v1/config/option-sets/{dmt['id']}/items/{item['id']}",
        json={"label": "DIRTY (audited relabel)"},
        headers=_auth(admin.token),
    )
    assert res.status_code == 200, res.text
    assert fetch_all(
        db_conn,
        """select 1 from public.audit_log where table_name = 'public.option_items' and row_id = :i
              and action = 'UPDATE' and actor_id = :a""",
        i=item["id"],
        a=admin.id,
    )

    # Nobody can rewrite or erase history.
    for sql in (
        "update public.audit_log set actor_id = null where row_id = :g",
        "delete from public.audit_log where row_id = :g",
    ):
        with pytest.raises(DBAPIError):
            db_attempt(session_factory, admin.id, sql, g=gs_id)
    assert {"table_name": "public.goods_slips", "action": "INSERT"} in fetch_all(
        db_conn,
        "select table_name, action from public.audit_log where row_id = :g",
        g=gs_id,
    )


# --- G-18 ----------------------------------------------------------------------------------------
async def test_g18_published_versions_are_immutable_and_pinned(
    client: AsyncClient,
    db_conn: Connection,
    storage: FakeStorage,
    actors: Actors,
    admin: Admin,
    masters: Masters,
    products: Products,
    session_factory: sessionmaker[Session],
) -> None:
    published = fetch_all(
        db_conn,
        """select v.id, v.snapshot::text as snapshot from public.form_versions v
             join public.form_definitions d on d.id = v.form_definition_id
            where d.code = 'S1_INSPECT_DMT' and v.status = 'PUBLISHED'""",
    )[0]
    # Editing a published version through the API is impossible: edits only target a draft.
    res = await client.put(
        "/api/v1/config/forms/S1_INSPECT_DMT/draft/fields",
        json={"fields": []},
        headers=_auth(admin.token),
    )
    assert res.status_code in (404, 409, 422), res.text
    for sql in (
        "update public.form_versions set snapshot = '{}'::jsonb where id = :v",
        "update public.form_versions set status = 'DRAFT' where id = :v",
        "delete from public.form_fields where form_version_id = :v",
    ):
        with pytest.raises(DBAPIError, match="G-18"):
            db_attempt(session_factory, admin.id, sql, v=published["id"])
    wf = fetch_all(
        db_conn,
        "select id from public.workflow_versions where status = 'PUBLISHED' limit 1",
    )[0]
    with pytest.raises(DBAPIError, match="G-18"):
        db_attempt(
            session_factory,
            admin.id,
            "update public.workflow_versions set snapshot = '{}'::jsonb where id = :v",
            v=wf["id"],
        )
    assert (
        fetch_all(
            db_conn,
            "select snapshot::text as snapshot from public.form_versions where id = :v",
            v=published["id"],
        )[0]["snapshot"]
        == published["snapshot"]
    )

    # Each transaction stores the version it was created under.
    gs_id, items = await gs_at(client, storage, actors, masters, [(products.dmt, 3, 3)])
    assert (
        await grade(client, admin.token, items[0], {"DMT_OK_PACKED": 3}, packaging=3)
    ).status_code == 200
    pins = fetch_all(
        db_conn,
        """select g.workflow_version_id, i.form_version_id
             from public.goods_slips g
             join public.gs_items gi on gi.gs_id = g.id
             join public.inspections i on i.gs_item_id = gi.id
            where g.id = :g""",
        g=gs_id,
    )[0]
    assert pins["workflow_version_id"] is not None
    assert str(pins["form_version_id"]) == str(published["id"])
    with pytest.raises(DBAPIError):
        db_attempt(
            session_factory,
            admin.id,
            "update public.goods_slips set workflow_version_id = null where id = :g",
            g=gs_id,
        )
    assert re.fullmatch(r"[0-9a-f-]{36}", str(pins["workflow_version_id"]))
