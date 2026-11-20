"""Integration tests for option sets and option items.

References master plan §3.2, §8.3, §10, prompt P1-07.
"""

from httpx import AsyncClient
from sqlalchemy import text

from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_list_and_get_option_sets(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    admin_id = users.create(super_admin=True)
    token = make_token(admin_id)

    res = await client.get("/api/v1/config/option-sets", headers=_auth(token))
    assert res.status_code == 200
    sets = res.json()
    assert len(sets) >= 35

    deliv_set = next(s for s in sets if s["code"] == "DELIVERY_MODE")
    assert deliv_set["name"] == "Delivery Mode / Transporter"
    assert len(deliv_set["items"]) == 3

    # Get by code
    res_code = await client.get("/api/v1/config/option-sets/DELIVERY_MODE", headers=_auth(token))
    assert res_code.status_code == 200
    assert res_code.json()["code"] == "DELIVERY_MODE"


async def test_admin_edits_label_and_verifies_audit(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn
) -> None:
    admin_id = users.create(super_admin=True)
    token = make_token(admin_id)

    # 1. Fetch DELIVERY_MODE option set
    res = await client.get("/api/v1/config/option-sets/DELIVERY_MODE", headers=_auth(token))
    assert res.status_code == 200
    deliv_set = res.json()
    set_id = deliv_set["id"]

    courier_item = next(i for i in deliv_set["items"] if i["code"] == "COURIER_PARCEL")
    item_id = courier_item["id"]
    assert courier_item["label"] == "Courier"  # seeded label since DEC-62 (gate v4)

    # 2. Update label to "Courier / Express Parcel"
    update_res = await client.put(
        f"/api/v1/config/option-sets/{set_id}/items/{item_id}",
        headers=_auth(token),
        json={"label": "Courier / Express Parcel"},
    )
    assert update_res.status_code == 200
    updated = update_res.json()
    assert updated["label"] == "Courier / Express Parcel"
    assert updated["code"] == "COURIER_PARCEL"  # Code is unchanged!

    # 3. Verify new label appears on GET
    fetch_res = await client.get("/api/v1/config/option-sets/DELIVERY_MODE", headers=_auth(token))
    refetched = next(i for i in fetch_res.json()["items"] if i["code"] == "COURIER_PARCEL")
    assert refetched["label"] == "Courier / Express Parcel"

    # 4. Verify config_change_log entry exists
    cur = (
        db_conn.execute(
            text(
                """
            select action, before->>'label' as before_label, after->>'label' as after_label
            from public.config_change_log
            where entity_type = 'option_item' and entity_id = :id
            order by changed_at desc limit 1
            """
            ),
            {"id": str(item_id)},
        )
        .mappings()
        .first()
    )
    assert cur is not None
    assert cur["action"] == "OPTION_ITEM_UPDATE"
    assert cur["before_label"] == "Courier"
    assert cur["after_label"] == "Courier / Express Parcel"


async def test_status_upgrade_requires_reason(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    admin_id = users.create(super_admin=True)
    token = make_token(admin_id)

    # DMT_OTHER_BRANDS has allowed_status = 'NO'
    res = await client.get("/api/v1/config/option-sets/DMT_CONDITION", headers=_auth(token))
    dmt_set = res.json()
    other_brand_item = next(i for i in dmt_set["items"] if i["code"] == "DMT_OTHER_BRANDS")
    item_id = other_brand_item["id"]
    assert other_brand_item["allowed_status"] == "NO"

    # Attempting to change to YES without a reason fails
    fail_res = await client.put(
        f"/api/v1/config/option-sets/{dmt_set['id']}/items/{item_id}",
        headers=_auth(token),
        json={"allowed_status": "YES"},
    )
    assert fail_res.status_code == 422
    assert fail_res.json()["error"]["code"] == "REASON_REQUIRED"

    # Providing a reason succeeds and logs OPTION_STATUS_UPGRADE
    ok_res = await client.put(
        f"/api/v1/config/option-sets/{dmt_set['id']}/items/{item_id}",
        headers=_auth(token),
        json={
            "allowed_status": "YES",
            "reason": "Special management approval for promotional campaign",
        },
    )
    assert ok_res.status_code == 200
    assert ok_res.json()["allowed_status"] == "YES"


async def test_hazard_option_cannot_be_changed_to_yes_g05(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    admin_id = users.create(super_admin=True)
    token = make_token(admin_id)

    # PRS_BROKEN_WITH_HG has system_behavior = 'HAZARD'
    res = await client.get("/api/v1/config/option-sets/PRISMATIC_CONDITION", headers=_auth(token))
    prs_set = res.json()
    hazard_item = next(i for i in prs_set["items"] if i["code"] == "PRS_BROKEN_WITH_HG")
    assert hazard_item["system_behavior"] == "HAZARD"

    # Even with reason and Super Admin privileges, G-05 rejects changing to YES
    g05_res = await client.put(
        f"/api/v1/config/option-sets/{prs_set['id']}/items/{hazard_item['id']}",
        headers=_auth(token),
        json={"allowed_status": "YES", "reason": "Attempting to bypass hazard rule"},
    )
    assert g05_res.status_code == 409
    err = g05_res.json()["error"]
    assert err["code"] == "G-05"


async def test_option_usage_counter(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    admin_id = users.create(super_admin=True)
    token = make_token(admin_id)

    res = await client.get("/api/v1/config/option-items/COURIER_PARCEL/usage", headers=_auth(token))
    assert res.status_code == 200
    data = res.json()
    assert data["code"] == "COURIER_PARCEL"
    assert isinstance(data["usage_count"], int)
    assert data["usage_count"] >= 0
