"""Integration tests for workflow configuration, number series, settings,
print templates, and history (prompt P1-08).
"""

from httpx import AsyncClient

from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_get_published_workflow_and_structure(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    admin_id = users.create(super_admin=True)
    token = make_token(admin_id)

    # 1. List workflows
    res = await client.get("/api/v1/config/workflow", headers=_auth(token))
    assert res.status_code == 200
    wfs = res.json()
    assert any(w["code"] == "RMS_STANDARD" for w in wfs)

    # 2. Get published snapshot
    snap_res = await client.get(
        "/api/v1/config/workflow/RMS_STANDARD/published", headers=_auth(token)
    )
    assert snap_res.status_code == 200
    snap = snap_res.json()
    assert snap["workflow_code"] == "RMS_STANDARD"
    # v2 since change plan 2026-11-12 Phase 3 (AMD-08): Carton Opening / Counting labels only.
    assert snap["version_no"] == 2
    labels = {s["code"]: s["label"] for s in snap["steps"]}
    assert labels["S1_UNBOX"] == "Step-2 Carton Opening"
    assert labels["S1_ITEMIZE"] == "Step-3 Counting & Categorisation"
    assert len(snap["stages"]) == 7
    assert len(snap["steps"]) == 15
    assert len(snap["transitions"]) == 19

    # Verify locked guards on transitions
    unbox_tr = next(
        t
        for t in snap["transitions"]
        if t["from_step_code"] == "S1_GATE" and t["to_step_code"] == "S1_UNBOX"
    )
    assert "G-01" in unbox_tr["system_guards"]


async def test_workflow_draft_publish_and_versioning(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    admin_id = users.create(super_admin=True)
    token = make_token(admin_id)

    # 1. Create draft from the published version (v2 since change plan Phase 3, AMD-08)
    published = (
        await client.get("/api/v1/config/workflow/RMS_STANDARD/published", headers=_auth(token))
    ).json()
    base = int(published["version_no"])
    draft_res = await client.post(
        "/api/v1/config/workflow/RMS_STANDARD/draft", headers=_auth(token)
    )
    assert draft_res.status_code == 200
    draft = draft_res.json()
    assert draft["version_no"] == base + 1
    assert draft["status"] == "DRAFT"

    # 2. Update a step label in draft
    step_res = await client.put(
        "/api/v1/config/workflow/RMS_STANDARD/draft/step-label",
        params={"step_code": "S1_GATE", "new_label": "Gate Inward Entry (Updated v2)"},
        headers=_auth(token),
    )
    assert step_res.status_code == 200

    # 3. Validate draft passes
    val_res = await client.post(
        "/api/v1/config/workflow/RMS_STANDARD/draft/validate", headers=_auth(token)
    )
    assert val_res.status_code == 200
    assert val_res.json()["is_valid"] is True

    # 4. Publish v2 with mandatory reason
    pub_res = await client.post(
        "/api/v1/config/workflow/RMS_STANDARD/draft/publish",
        json={"reason": "Updated Gate Inward label for clarity"},
        headers=_auth(token),
    )
    assert pub_res.status_code == 200
    pub_data = pub_res.json()
    assert pub_data["version_no"] == base + 1
    assert pub_data["status"] == "PUBLISHED"

    # 5. Confirm v1 is still retrievable (immutable history)
    v1_res = await client.get(
        "/api/v1/config/workflow/RMS_STANDARD/versions/1", headers=_auth(token)
    )
    assert v1_res.status_code == 200
    assert v1_res.json()["version_no"] == 1
    v1_gate = next(s for s in v1_res.json()["steps"] if s["code"] == "S1_GATE")
    assert v1_gate["label"] == "Step-1 GS creation"

    # 6. Diff the previous published version vs the new one
    diff_res = await client.get(
        "/api/v1/config/workflow/RMS_STANDARD/diff",
        params={"v1": base, "v2": base + 1},
        headers=_auth(token),
    )
    assert diff_res.status_code == 200
    diff = diff_res.json()
    assert len(diff["steps_diff"]["changed"]) == 1
    assert diff["steps_diff"]["changed"][0]["code"] == "S1_GATE"
    assert diff["steps_diff"]["changed"][0]["before"] == "Step-1 GS creation"
    assert diff["steps_diff"]["changed"][0]["after"] == "Gate Inward Entry (Updated v2)"

    # The Phase 3 relabel (v1 -> v2) changed exactly two step labels and nothing else (AMD-08).
    relabel = (
        await client.get(
            "/api/v1/config/workflow/RMS_STANDARD/diff",
            params={"v1": 1, "v2": 2},
            headers=_auth(token),
        )
    ).json()
    assert {c["code"] for c in relabel["steps_diff"]["changed"]} == {"S1_UNBOX", "S1_ITEMIZE"}


async def test_workflow_locked_system_guard_cannot_be_removed(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    admin_id = users.create(super_admin=True)
    token = make_token(admin_id)

    # 1. Create or get draft
    draft_res = await client.post(
        "/api/v1/config/workflow/RMS_STANDARD/draft", headers=_auth(token)
    )
    assert draft_res.status_code == 200
    draft = draft_res.json()

    # Find the transition from S1_GATE to S1_UNBOX
    s1_gate = next(s for s in draft["steps"] if s["code"] == "S1_GATE")
    s1_unbox = next(s for s in draft["steps"] if s["code"] == "S1_UNBOX")

    # Attempt to update transitions by removing locked guard G-01
    bad_transitions = [
        {
            "from_step_id": s1_gate["id"],
            "to_step_id": s1_unbox["id"],
            "condition": None,
            "system_guards": [],  # Stripped G-01!
            "priority": 10,
        }
    ]

    res = await client.put(
        "/api/v1/config/workflow/RMS_STANDARD/draft/transitions",
        json=bad_transitions,
        headers=_auth(token),
    )
    assert res.status_code == 422
    data = res.json()
    assert data["error"]["code"] == "SYSTEM_GUARD_LOCKED"
    assert "G-01" in data["error"]["message"]


async def test_number_series_preview_and_rollover(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    admin_id = users.create(super_admin=True)
    token = make_token(admin_id)

    # 1. List number series - check GS has DEC-01 marker
    res = await client.get("/api/v1/config/numbering", headers=_auth(token))
    assert res.status_code == 200
    series = res.json()
    gs_series = next(s for s in series if s["code"] == "GS")
    assert gs_series["is_provisional_gs"] is True

    # 2. Preview 31-Mar-2026 (last day of FY 2025-26)
    p1 = await client.get(
        "/api/v1/config/numbering/GS/preview",
        params={"count": 3, "on_date": "2026-03-31"},
        headers=_auth(token),
    )
    assert p1.status_code == 200
    d1 = p1.json()
    assert d1["fy_string"] == "2025-26"
    assert d1["next_numbers"][0].startswith("GS/2025-26/")

    # 3. Preview 01-Apr-2026 (first day of FY 2026-27 rollover)
    p2 = await client.get(
        "/api/v1/config/numbering/GS/preview",
        params={"count": 3, "on_date": "2026-04-01"},
        headers=_auth(token),
    )
    assert p2.status_code == 200
    d2 = p2.json()
    assert d2["fy_string"] == "2026-27"
    assert d2["next_numbers"][0].startswith("GS/2026-27/")


async def test_system_settings_public_and_provisional_rules(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    admin_id = users.create(super_admin=True)
    token = make_token(admin_id)

    # 1. Public settings endpoint (unauthenticated)
    pub_res = await client.get("/api/v1/config/settings/public")
    assert pub_res.status_code == 200
    pub = pub_res.json()
    assert "app_name" in pub
    assert "branding_primary_color" in pub

    # 2. Provisional rules list
    prov_res = await client.get(
        "/api/v1/config/settings",
        params={"category": "provisional"},
        headers=_auth(token),
    )
    assert prov_res.status_code == 200
    prov_settings = prov_res.json()
    assert len(prov_settings) >= 15
    assert any(s["source_ref"] == "DEC-02" for s in prov_settings)
    assert any(s["source_ref"] == "DEC-12" for s in prov_settings)

    # 3. Color contrast check
    cc_res = await client.post(
        "/api/v1/config/settings/branding/contrast-check",
        json={"foreground_color": "#ffffff", "background_color": "#0f172a"},
        headers=_auth(token),
    )
    assert cc_res.status_code == 200
    contrast = cc_res.json()
    assert contrast["contrast_ratio"] >= 7.0
    assert contrast["normal_text_aa"] is True


async def test_print_templates_and_sample_preview(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    admin_id = users.create(super_admin=True)
    token = make_token(admin_id)

    # 1. List templates
    res = await client.get("/api/v1/config/templates", headers=_auth(token))
    assert res.status_code == 200
    tpls = res.json()
    assert len(tpls) == 7  # + DISPATCH_SLIP (change plan Phase 8, AMD-19)
    codes = {t["code"] for t in tpls}
    assert codes == {
        "REPLACEMENT_SLIP",
        "GS_TAG",
        "TRANSFER_NOTE",
        "STORE_ISSUE",
        "CN_SUMMARY",
        "AC_ACTIONS_SLIP",
        "DISPATCH_SLIP",
    }

    # 2. Get sample preview data
    samp_res = await client.get(
        "/api/v1/config/templates/REPLACEMENT_SLIP/sample-data",
        headers=_auth(token),
    )
    assert samp_res.status_code == 200
    samp = samp_res.json()
    assert samp["sample_data"]["is_sample_preview"] is True
    assert "Acme Healthcare" in samp["sample_data"]["party_name"]


async def test_config_history_and_system_guards(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    admin_id = users.create(super_admin=True)
    token = make_token(admin_id)

    # 1. Static system guards (G-01..G-18, + G-19..G-22 from the 2026-11 change request)
    guards_res = await client.get("/api/v1/config/system-guards", headers=_auth(token))
    assert guards_res.status_code == 200
    guards = guards_res.json()
    assert len(guards) == 22
    assert guards[0]["code"] == "G-01"
    assert guards[-1]["code"] == "G-22"

    # Also test /admin/system-guards alias
    guards_alias = await client.get("/api/v1/admin/system-guards", headers=_auth(token))
    assert guards_alias.status_code == 200
    assert len(guards_alias.json()) == 22

    # 2. Config change history
    hist_res = await client.get("/api/v1/config/history", headers=_auth(token))
    assert hist_res.status_code == 200
    hist = hist_res.json()
    assert "items" in hist
    assert "total" in hist
