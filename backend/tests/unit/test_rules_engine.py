import json
from pathlib import Path

from app.shared.rules_engine import evaluate_rule, evaluate_validation


def test_shared_rules_test_vectors() -> None:
    vectors_path = Path(__file__).resolve().parents[3] / "shared" / "rules-test-vectors.json"
    assert vectors_path.exists(), f"Missing test vectors at {vectors_path}"

    with open(vectors_path, encoding="utf-8") as f:
        data = json.load(f)

    cases = data["cases"]
    assert len(cases) >= 40, f"Expected >= 40 test cases, found {len(cases)}"

    for case in cases:
        case_id = case["id"]
        rule = case.get("rule")
        values = case.get("values", {})
        context = case.get("context")

        if rule is not None:
            expected = case["expected"]
            actual = evaluate_rule(rule, values, context)
            assert actual == expected, (
                f"Failed case {case_id}: expected {expected}, got {actual} "
                f"with rule={rule}, values={values}, context={context}"
            )

        if "validation_spec" in case:
            val_spec = case["validation_spec"]
            field_val = case.get("field_value")
            exp_valid = case["expected_valid"]
            exp_err = case.get("expected_error")

            errors = evaluate_validation(
                val_spec,
                field_val,
                values,
                is_required=case.get("is_required", False),
                context=context,
            )
            is_valid = len(errors) == 0
            assert is_valid == exp_valid, (
                f"Failed validation case {case_id}: expected valid={exp_valid}, "
                f"got errors={errors} with spec={val_spec}, val={field_val}"
            )
            if exp_err:
                assert any(exp_err in err for err in errors), (
                    f"Failed validation error text {case_id}: expected '{exp_err}', got {errors}"
                )
