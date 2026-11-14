"""Product CSV import planner (pure). Change plan 2026-11-12 Phase 1 · AMD-07 · DEC-36."""

import pytest

from app.modules.masters.product_import import (
    CategoryRef,
    CsvFormatError,
    MastersSnapshot,
    ProductRef,
    SubCategoryRef,
    code_from_name,
    parse_csv,
    plan_import,
)

MASTERS = MastersSnapshot(
    categories=[
        CategoryRef("PRISMATIC", "PRISMATIC", True),
        CategoryRef("OLD", "Retired", False),
    ],
    subcategories=[
        SubCategoryRef("PRISMATIC", "BLISTER", "Blister Pack", True),
        SubCategoryRef("PRISMATIC", "GONE", "Gone", False),
    ],
    products=[
        ProductRef("p1", "ITM-00001", "Akutem", "PRISMATIC", None),
        ProductRef("p2", "ITM-00002", "Twin", "PRISMATIC", None),
        ProductRef("p3", "ITM-00003", "TWIN", "PRISMATIC", None),
    ],
)


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("Rectal (Blister Pack)", "RECTAL_BLISTER_PACK"),
        ("  Large (HutShape,  Wall Type) ", "LARGE_HUTSHAPE_WALL_TYPE"),
        ("3-in-1", "C_3_IN_1"),
        ("***", ""),
    ],
)
def test_code_from_name(name: str, code: str) -> None:
    assert code_from_name(name) == code


def test_parse_accepts_header_aliases_and_any_order() -> None:
    rows = parse_csv("﻿Category,Sub-Category,Product Name\nA, B ,  Item  One \n\n")
    assert len(rows) == 1
    assert (rows[0].item_name, rows[0].category, rows[0].sub_category) == ("Item One", "A", "B")
    assert rows[0].uom == "PCS" and rows[0].row_no == 2


def test_parse_requires_item_and_category_columns() -> None:
    with pytest.raises(CsvFormatError, match="Item Name"):
        parse_csv("Category,Sub-Category\nA,B\n")


def test_plan_matches_by_code_or_name_and_flags_problems() -> None:
    rows = parse_csv(
        "Item Name,Category,Sub-Category\n"
        "akutem,prismatic,blister pack\n"  # update: category by code, sub by name
        "New One,PRISMATIC,BLISTER\n"  # insert: sub by code
        "Twin,PRISMATIC,\n"  # ambiguous existing name
        "X,Retired,\n"  # inactive category
        "Y,PRISMATIC,Gone\n"  # inactive sub-category
        "Z,PRISMATIC,Brand New Sub\n"  # creates a sub-category
    )
    plan = plan_import(rows, MASTERS, create_categories=False)
    assert [(u.product_code, u.to_subcategory) for u in plan.updates] == [("ITM-00001", "BLISTER")]
    assert [(p.name, p.subcategory_code) for p in plan.new_products] == [
        ("New One", "BLISTER"),
        ("Z", "BRAND_NEW_SUB"),
    ]
    assert [s.code for s in plan.new_subcategories] == ["BRAND_NEW_SUB"]
    reasons = [e.reason for e in plan.exceptions]
    assert any("more than one product" in r for r in reasons)
    assert any("Category 'OLD' is inactive" in r for r in reasons)
    assert any("Sub-category 'GONE' is inactive" in r for r in reasons)


def test_plan_conflicting_duplicate_rows_are_exceptions() -> None:
    rows = parse_csv(
        "Item Name,Category,Sub-Category\nN,PRISMATIC,A\nN,PRISMATIC,A\nN,PRISMATIC,B\n"
    )
    plan = plan_import(rows, MASTERS, create_categories=False)
    assert len(plan.new_products) == 1
    assert plan.duplicates_in_file == 1
    assert len(plan.exceptions) == 1
    # Sub-category B is only used by the rejected row, so it is not created.
    assert [s.code for s in plan.new_subcategories] == ["A"]
