import json

import pulp
import pytest

from finalops import Ledger, Model, build_debug_bundle, run


def _production_plan():
    ledger = Ledger()
    ledger.add(id="widgets_qty", description="widgets per week", source="brief:1", kind="decision_variable", units="units/week")
    ledger.add(id="cost", description="minimize cost", source="brief:2", kind="objective")
    ledger.add(id="demand", description="at least 100 units", source="brief:3")
    ledger.add(id="capacity", description="at most 240 capacity", source="brief:4")
    ledger.add(id="unused_rule", description="never wired up", source="brief:5")

    model = Model("plan", ledger)
    x = model.add_variable(pulp.LpVariable("widgets", lowBound=0), requirement_id="widgets_qty", units="units/week")
    y = pulp.LpVariable("gadgets", lowBound=0)
    model.set_objective(3 * x + 5 * y, requirement_id="cost")
    model.add_constraint(x + y >= 100, requirement_id="demand")
    model.add_constraint(x + 2 * y <= 240, requirement_id="capacity")
    return model


def _conflict():
    ledger = Ledger()
    ledger.add(id="cost", description="minimize", source="b:1", kind="objective")
    ledger.add(id="floor", description="at least 100", source="b:2")
    ledger.add(id="ceiling", description="at most 40", source="b:3")
    model = Model("conflict", ledger)
    x = pulp.LpVariable("x", lowBound=0)
    model.set_objective(x, requirement_id="cost")
    model.add_constraint(x >= 100, requirement_id="floor")
    model.add_constraint(x <= 40, requirement_id="ceiling")
    return model


def test_bundle_is_json_serializable_and_written(tmp_path):
    out = tmp_path / "bundle.json"
    bundle = build_debug_bundle(_production_plan(), out=out)
    assert json.loads(out.read_text()) == json.loads(json.dumps(bundle))
    assert bundle["schema_version"] == 1


def test_feasible_bundle_reports_slack_binding_and_shadow_prices():
    bundle = build_debug_bundle(_production_plan())
    assert bundle["summary"]["status"] == "Optimal"
    assert bundle["summary"]["objective"] == pytest.approx(300.0)
    assert bundle["summary"]["proven_optimal"] is True

    by_req = {c["requirement_id"]: c for c in bundle["constraints"]}
    assert by_req["demand"]["binding"] is True
    assert by_req["demand"]["shadow_price"] == pytest.approx(3.0)
    assert by_req["demand"]["sense"] == ">="
    assert by_req["demand"]["rhs"] == pytest.approx(100.0)
    assert by_req["capacity"]["binding"] is False
    assert by_req["capacity"]["slack"] == pytest.approx(140.0)
    assert by_req["capacity"]["terms"] == {"widgets": 1, "gadgets": 2}


def test_bundle_carries_variables_objective_and_ledger():
    bundle = build_debug_bundle(_production_plan())
    widgets = next(v for v in bundle["variables"] if v["name"] == "widgets")
    assert widgets["requirement_id"] == "widgets_qty"
    assert widgets["units"] == "units/week"
    assert widgets["value"] == pytest.approx(100.0)

    assert bundle["objective"]["requirement_id"] == "cost"
    assert bundle["objective"]["terms"] == {"widgets": 3, "gadgets": 5}
    assert {r["id"] for r in bundle["requirements"]} == {"widgets_qty", "cost", "demand", "capacity", "unused_rule"}
    assert bundle["summary"]["unlinked_requirements"] == ["unused_rule"]


def test_what_if_dropped_is_precomputed_per_constraint():
    bundle = build_debug_bundle(_production_plan())
    by_req = {c["requirement_id"]: c for c in bundle["constraints"]}
    assert by_req["capacity"]["what_if_dropped"] == {"status": "Optimal", "objective": pytest.approx(300.0)}
    assert by_req["demand"]["what_if_dropped"] == {"status": "Optimal", "objective": pytest.approx(0.0)}


def test_what_if_can_be_skipped():
    bundle = build_debug_bundle(_production_plan(), include_what_if=False)
    assert all(c["what_if_dropped"] is None for c in bundle["constraints"])


def test_infeasible_bundle_explains_and_finds_single_rule_fixes():
    bundle = build_debug_bundle(_conflict())
    assert bundle["summary"]["status"] == "Infeasible"
    assert bundle["summary"]["feasible"] is False
    assert bundle["summary"]["objective"] is None
    assert all(v["value"] is None for v in bundle["variables"])

    assert bundle["infeasibility"]["violations"][0]["requirement_id"] in {"floor", "ceiling"}
    assert any(c["violation"] for c in bundle["constraints"])
    # Dropping either one of the two conflicting rules makes the model solvable.
    assert all(c["what_if_dropped"]["status"] == "Optimal" for c in bundle["constraints"])
    assert all(c["slack"] is None for c in bundle["constraints"])


def test_mip_shadow_prices_are_tagged_lp_relaxation():
    ledger = Ledger()
    ledger.add(id="value", description="maximize", source="b:1", kind="objective")
    ledger.add(id="cap", description="capacity", source="b:2")
    model = Model("knap", ledger, sense=pulp.LpMaximize)
    xs = [pulp.LpVariable(f"x{i}", cat="Binary") for i in range(3)]
    model.set_objective(pulp.lpSum(v * x for v, x in zip([10, 8, 5], xs)), requirement_id="value")
    model.add_constraint(pulp.lpSum(w * x for w, x in zip([5, 4, 3], xs)) <= 7, requirement_id="cap")

    bundle = build_debug_bundle(model)
    assert bundle["summary"]["sense"] == "max"
    assert bundle["constraints"][0]["shadow_basis"] == "lp_relaxation"
    assert {v["category"] for v in bundle["variables"]} == {"Binary"}


def test_unbounded_model_is_reported_as_unbounded_not_infeasible():
    ledger = Ledger()
    ledger.add(id="profit", description="maximize", source="b:1", kind="objective")
    ledger.add(id="floor", description="at least 10", source="b:2")
    model = Model("unbounded", ledger, sense=pulp.LpMaximize)
    x = pulp.LpVariable("x", lowBound=0)
    model.set_objective(2 * x, requirement_id="profit")
    model.add_constraint(x >= 10, requirement_id="floor")

    outcome = run(model, out=None)
    assert any(p.startswith("unbounded") for p in outcome.problems)
    assert not any(p.startswith("infeasible") for p in outcome.problems)

    bundle = build_debug_bundle(model)
    assert bundle["summary"]["status"] == "Unbounded"
    assert bundle["summary"]["objective"] is None
    assert all(v["value"] is None for v in bundle["variables"])


def test_infeasible_bundle_marks_the_conflict():
    bundle = build_debug_bundle(_conflict())
    conflict = bundle["infeasibility"]["conflict"]

    assert conflict["minimal"] is True
    assert set(conflict["requirement_ids"]) == {"floor", "ceiling"}
    assert all(c["in_conflict"] is True for c in bundle["constraints"])


def test_feasible_bundle_has_no_conflict_flags():
    bundle = build_debug_bundle(_production_plan())
    assert bundle["infeasibility"] is None
    assert all(c["in_conflict"] is None for c in bundle["constraints"])
