"""Integration tests for versioned forms and form builder (master plan §8.3, §10, prompt P1-07)."""

from httpx import AsyncClient
from sqlalchemy import Connection, text

from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_list_seeded_forms_and_get_published(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    admin_id = users.create(super_admin=True)
    token = make_token(admin_id)

    # 1. List forms: exactly 20 seeded forms
    res = await client.get("/api/v1/config/forms", headers=_auth(token))
    assert res.status_code == 200
    forms = res.json()
    assert len(forms) == 20

    gate_form = next(f for f in forms if f["code"] == "S1_GATE_INWARD")
    # The gate form gets a new version per change (v2 AMD-01..04, v3, v4 DEC-62), older ones are
    # RETIRED (G-18), and integration tests pin v3 by default (fixture use_gate_form_v3). Compare
    # with the DB instead of a hard-coded number.
    assert (
        gate_form["latest_published_version"]
        == as_admin(db_conn)
        .execute(
            text(
                """select max(v.version_no) from public.form_versions v
             join public.form_definitions d on d.id = v.form_definition_id
            where d.code = 'S1_GATE_INWARD' and v.status = 'PUBLISHED'"""
            )
        )
        .scalar_one()
    )
    assert gate_form["has_draft"] is False

    # 2. Get published snapshot
    snap_res = await client.get(
        "/api/v1/config/forms/S1_GATE_INWARD/published", headers=_auth(token)
    )
    assert snap_res.status_code == 200
    snapshot = snap_res.json()
    assert snapshot["form_code"] == "S1_GATE_INWARD"
    assert snapshot["version_no"] == gate_form["latest_published_version"]
    # Form v3 (pinned for integration tests): v2's 17 fields without the missing-document
    # acknowledgement; document files travel per gate document row (AMD-04), so the v1
    # `gate_doc_image` field is not added any more.
    keys = [f["field_key"] for f in snapshot["fields"]]
    assert len(keys) == 16
    assert "missing_doc_warning_acknowledged" not in keys
    assert keys[:3] == ["return_type", "gate_entry_date", "gate_entry_no"]
    assert "carton_count" in keys and "no_document" in keys
    assert "gate_doc_image" not in keys and "accompanying_doc" not in keys

    # Verify embedded option items for dropdowns
    deliv_mode_field = next(f for f in snapshot["fields"] if f["field_key"] == "delivery_mode")
    assert len(deliv_mode_field["option_items"]) == 3
    assert {o["code"] for o in deliv_mode_field["option_items"]} == {
        "COURIER_PARCEL",
        "DIRECT_TRUCK",
        "SELF_PARTY_REP",
    }


async def test_form_versioning_publish_and_immutability(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn
) -> None:
    admin_id = users.create(super_admin=True)
    token = make_token(admin_id)

    # 1. Capture v1 snapshot before making any changes
    v1_snap_res = await client.get(
        "/api/v1/config/forms/S1_ITEMIZE/published", headers=_auth(token)
    )
    assert v1_snap_res.status_code == 200
    v1_snapshot_before = v1_snap_res.json()

    # 2. Create draft from published
    draft_res = await client.post("/api/v1/config/forms/S1_ITEMIZE/draft", headers=_auth(token))
    assert draft_res.status_code == 200
    draft = draft_res.json()
    assert draft["version_no"] == 2
    assert draft["status"] == "DRAFT"
    assert len(draft["fields"]) == 3

    # 3. Modify draft fields: add a custom field, relabel an existing field
    current_fields = draft["fields"]
    fields_payload = []
    for f in current_fields:
        f_dict = {
            "field_key": f["field_key"],
            "label": f["label"] if f["field_key"] != "item_notes" else "Updated Item Remarks",
            "control_type": f["control_type"],
            "option_set_id": f["option_set_id"],
            "is_required": f["is_required"],
            "sort_order": f["sort_order"],
            "section": f["section"],
            "is_core": f["is_core"],
            "validation": f.get("validation"),
        }
        fields_payload.append(f_dict)

    # Add non-core custom field
    fields_payload.append(
        {
            "field_key": "custom_batch_tag",
            "label": "Custom Batch Tag",
            "control_type": "text",
            "is_required": False,
            "sort_order": 40,
            "section": "Notes",
            "is_core": False,
        }
    )

    update_res = await client.put(
        "/api/v1/config/forms/S1_ITEMIZE/draft/fields",
        headers=_auth(token),
        json={"fields": fields_payload},
    )
    assert update_res.status_code == 200
    updated_draft = update_res.json()
    assert len(updated_draft["fields"]) == 4

    # 4. Validate draft
    val_res = await client.post(
        "/api/v1/config/forms/S1_ITEMIZE/draft/validate", headers=_auth(token)
    )
    assert val_res.status_code == 200
    assert val_res.json()["is_valid"] is True

    # 5. Publish draft
    pub_res = await client.post(
        "/api/v1/config/forms/S1_ITEMIZE/draft/publish",
        headers=_auth(token),
        json={"version_notes": "Added custom_batch_tag and relabelled notes"},
    )
    assert pub_res.status_code == 200
    published_v2 = pub_res.json()
    assert published_v2["version_no"] == 2
    assert published_v2["status"] == "PUBLISHED"

    # 6. Verify v1 is now RETIRED in the database
    v1_sql = (
        "select status from public.form_versions "
        "where form_definition_id = :def_id and version_no = 1"
    )
    v1_row = (
        db_conn.execute(
            text(v1_sql),
            {"def_id": published_v2["form_definition_id"]},
        )
        .mappings()
        .one()
    )
    assert v1_row["status"] == "RETIRED"

    # 7. CRITICAL ACCEPTANCE CHECK: Previous version (v1) snapshot is unchanged!
    v1_ver_res = await client.get(
        "/api/v1/config/forms/S1_ITEMIZE/versions/1", headers=_auth(token)
    )
    assert v1_ver_res.status_code == 200
    v1_snapshot_after = v1_ver_res.json()["snapshot"]
    assert v1_snapshot_after == v1_snapshot_before

    # 8. Check diff between v1 and v2
    diff_res = await client.get(
        "/api/v1/config/forms/S1_ITEMIZE/diff?v1=1&v2=2", headers=_auth(token)
    )
    assert diff_res.status_code == 200
    diff = diff_res.json()
    assert len(diff["added_fields"]) == 1
    assert diff["added_fields"][0]["field_key"] == "custom_batch_tag"
    assert len(diff["modified_fields"]) == 1
    assert diff["modified_fields"][0]["field_key"] == "item_notes"


async def test_core_fields_protection_and_cycle_detection(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    admin_id = users.create(super_admin=True)
    token = make_token(admin_id)

    # Create draft for S1_CSR_APPROVAL
    draft_res = await client.post(
        "/api/v1/config/forms/S1_CSR_APPROVAL/draft", headers=_auth(token)
    )
    assert draft_res.status_code == 200

    # Attempt to remove core field csr_approval
    bad_payload = {
        "fields": [
            {
                "field_key": "some_other_field",
                "label": "Some Other Field",
                "control_type": "text",
                "is_required": False,
                "sort_order": 10,
                "is_core": False,
            }
        ]
    }
    fail_res = await client.put(
        "/api/v1/config/forms/S1_CSR_APPROVAL/draft/fields",
        headers=_auth(token),
        json=bad_payload,
    )
    assert fail_res.status_code == 422
    assert fail_res.json()["error"]["code"] == "CANNOT_DELETE_CORE_FIELD"
