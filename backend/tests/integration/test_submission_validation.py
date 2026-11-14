"""Integration tests for submission validation across seeded v1 forms.

References master plan §4.2, §10, prompt P1-07.
"""

import pytest
from httpx import AsyncClient

from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory


@pytest.fixture
def auth(users: UserFactory, make_token: JwtFactory) -> dict[str, str]:
    """validate-submission requires an active signed-in user (production audit 2026-11-14)."""
    return {"Authorization": f"Bearer {make_token(users.create())}"}


async def test_s1_gate_inward_delivery_mode_conditional_validation(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    # 1. Payload with DIRECT_TRUCK missing vehicle_no and transporter_name
    invalid_truck_payload = {
        "values": {
            "state": "Uttar Pradesh",
            "station": "Agra",
            "party_name": "Demo Party One",
            # Form v2 (change plan 2026-11-12 Phase 2, AMD-01..AMD-04)
            "return_type": "ECOMMERCE_RETURN",
            "carton_count": 2,
            "delivery_mode": "DIRECT_TRUCK",
            # vehicle_no and transporter_name omitted
            "no_document": False,
            "gs_creation_format": "AUTO_STANDARD",
        }
    }
    res = await client.post(
        "/api/v1/config/forms/S1_GATE_INWARD/validate-submission",
        headers=auth,
        json=invalid_truck_payload,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_valid"] is False
    assert "vehicle_no" in data["errors"]
    assert "transporter_name" in data["errors"]
    # Courier fields should NOT have errors because they are not visible
    assert "courier_name" not in data["errors"]
    # DEC-39: E-Commerce hides the gate entry fields, so they are not required.
    assert "gate_entry_date" not in data["errors"] and "gate_entry_no" not in data["errors"]

    # 2. Complete valid truck payload succeeds
    valid_truck_payload = {
        "values": {
            "state": "Uttar Pradesh",
            "station": "Agra",
            "party_name": "Demo Party One",
            "return_type": "ECOMMERCE_RETURN",
            "carton_count": 2,
            "delivery_mode": "DIRECT_TRUCK",
            "vehicle_no": "UP-80-AB-1234",
            "transporter_name": "Agra Freight Lines",
            "no_document": False,
            "gs_creation_format": "AUTO_STANDARD",
        }
    }
    res_ok = await client.post(
        "/api/v1/config/forms/S1_GATE_INWARD/validate-submission",
        headers=auth,
        json=valid_truck_payload,
    )
    assert res_ok.status_code == 200
    data_ok = res_ok.json()
    assert data_ok["is_valid"] is True
    assert not data_ok["errors"]
    assert data_ok["sanitized_values"]["vehicle_no"] == "UP-80-AB-1234"


async def test_s1_inspect_dmt_extraction_sum_equals(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    # Allocated qty = 100, but packaging (40) + container (50) = 90 != 100
    mismatch_payload = {
        "values": {
            "visual_condition": "DMT_OK_PACKED",
            "extraction_type": "PACKAGING_EXTRACTED",
            "packaging_extracted_qty": 40,
            "container_extracted_qty": 50,
            "allocated_qty": 100,
        }
    }
    res = await client.post(
        "/api/v1/config/forms/S1_INSPECT_DMT/validate-submission",
        headers=auth,
        json=mismatch_payload,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_valid"] is False
    assert "allocated_qty" in data["errors"]

    # Matching sum: 40 + 60 = 100
    match_payload = {
        "values": {
            "visual_condition": "DMT_OK_PACKED",
            "extraction_type": "PACKAGING_EXTRACTED",
            "packaging_extracted_qty": 40,
            "container_extracted_qty": 60,
            "allocated_qty": 100,
        }
    }
    res_ok = await client.post(
        "/api/v1/config/forms/S1_INSPECT_DMT/validate-submission",
        headers=auth,
        json=match_payload,
    )
    assert res_ok.status_code == 200
    assert res_ok.json()["is_valid"] is True


async def test_s3_tech_receive_battery_replaced_conditional(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    # BATTERY_REPLACED requires pieces_checked, batteries_installed, and battery_type
    incomplete_payload = {
        "values": {
            "battery_check": "BATTERY_REPLACED",
            "cleaning_treatment": "CLEANED_SELLABLE",
            "post_servicing_classification": "FUNCTIONAL_GOOD",
        }
    }
    res = await client.post(
        "/api/v1/config/forms/S3_TECH_RECEIVE/validate-submission",
        headers=auth,
        json=incomplete_payload,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_valid"] is False
    assert "pieces_checked" in data["errors"]
    assert "batteries_installed" in data["errors"]
    assert "battery_type" in data["errors"]

    # When BATTERY_OK, batteries_installed and battery_type are not visible/required
    ok_payload = {
        "values": {
            "battery_check": "BATTERY_OK",
            "pieces_checked": 5,
            "cleaning_treatment": "CLEANED_SELLABLE",
            "post_servicing_classification": "FUNCTIONAL_GOOD",
        }
    }
    res_ok = await client.post(
        "/api/v1/config/forms/S3_TECH_RECEIVE/validate-submission",
        headers=auth,
        json=ok_payload,
    )
    assert res_ok.status_code == 200
    assert res_ok.json()["is_valid"] is True


async def test_s4_dismantle_pcb_conditional(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    # Part type PCB requires model_name and supplier_name
    pcb_missing = {
        "values": {
            "part_type": "PCB",
            "parts_storage_separation": "DEDICATED_CONTAINERS",
            "container_barcode": "BIN-01-A",
            "scrap_disposal_marked": True,
        }
    }
    res = await client.post(
        "/api/v1/config/forms/S4_DISMANTLE/validate-submission",
        headers=auth,
        json=pcb_missing,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_valid"] is False
    assert "model_name" in data["errors"]
    assert "supplier_name" in data["errors"]

    # Part type TIP does NOT require model_name or supplier_name
    tip_payload = {
        "values": {
            "part_type": "TIP",
            "parts_storage_separation": "DEDICATED_CONTAINERS",
            "container_barcode": "BIN-02-B",
            "scrap_disposal_marked": True,
        }
    }
    res_tip = await client.post(
        "/api/v1/config/forms/S4_DISMANTLE/validate-submission",
        headers=auth,
        json=tip_payload,
    )
    assert res_tip.status_code == 200
    assert res_tip.json()["is_valid"] is True


async def test_s6_accounts_cn_gst_not_reflected_restriction(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    # GST_NOT_REFLECTED with GST_CN is restricted (only GENERAL_CN allowed)
    restricted_payload = {
        "values": {
            "party_doc_verification": "PARTY_INVOICE",
            "gst_portal_verification": "GST_NOT_REFLECTED",
            "cn_type": "GST_CN",
            "rate_verification_ref": "RATE_SALES",
            "verified_rate": 150.0,
            "cn_number": "CN-2026-001",
            "cn_date": "2026-01-15",
            "cn_valuation": 1500.0,
        }
    }
    res = await client.post(
        "/api/v1/config/forms/S6_ACCOUNTS_CN/validate-submission",
        headers=auth,
        json=restricted_payload,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_valid"] is False
    assert "cn_type" in data["errors"]

    # With GENERAL_CN, validation passes
    ok_payload = {
        "values": {
            "party_doc_verification": "PARTY_INVOICE",
            "gst_portal_verification": "GST_NOT_REFLECTED",
            "cn_type": "GENERAL_CN",
            "rate_verification_ref": "RATE_SALES",
            "verified_rate": 150.0,
            "cn_number": "CN-2026-001",
            "cn_date": "2026-01-15",
            "cn_valuation": 1500.0,
        }
    }
    res_ok = await client.post(
        "/api/v1/config/forms/S6_ACCOUNTS_CN/validate-submission",
        headers=auth,
        json=ok_payload,
    )
    assert res_ok.status_code == 200
    assert res_ok.json()["is_valid"] is True
