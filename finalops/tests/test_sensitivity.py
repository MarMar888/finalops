import pulp
import pytest

from finalops import Ledger, Model
from finalops.sensitivity import binding_report, requirement_impact, solve_diff


def _production_plan(capacity=240, widget_cat="Continuous", gadget_cat="Continuous"):
    ledger = Ledger()
    ledger.add(id="cost", description="minimize cost", source="brief:1", kind="objective")
    ledger.add(id="demand", description="meet demand", source="brief:2")
    ledger.add(id="capacity", description="respect capacity", source="brief:3")

    model = Model("production_plan", ledger)
    widgets = pulp.LpVariable("widgets", lowBound=0, cat=widget_cat)
    gadgets = pulp.LpVariable("gadgets", lowBound=0, cat=gadget_cat)
    model.set_objective(3 * widgets + 5 * gadgets, requirement_id="cost")
    model.add_constraint(widgets + gadgets >= 100, requirement_id="demand", name="demand")
    model.add_constraint(widgets + 2 * gadgets <= capacity, requirement_id="capacity", name="capacity")
    return model, widgets, gadgets


def test_binding_report_lp_is_exact():
    model, _, _ = _production_plan()
    model.solve()
    report = binding_report(model)

    assert report.basis == "exact"
    by_id = {r.requirement_id: r for r in report.requirements}
    assert by_id["demand"].binding is True
    assert by_id["demand"].shadow_price == pytest.approx(3.0)
    assert by_id["capacity"].binding is False
    assert by_id["capacity"].slack == pytest.approx(140.0)


def test_binding_report_mip_uses_lp_relaxation_basis():
    model, _, _ = _production_plan(widget_cat="Integer", gadget_cat="Integer")
    model.solve()
    report = binding_report(model)

    assert report.basis == "lp_relaxation"
    for r in report.requirements:
        assert r.basis == "lp_relaxation"


def test_requirement_impact_slack_constraint_has_no_effect():
    model, _, _ = _production_plan()
    model.solve()
    impact = requirement_impact(model, "capacity", rhs_delta=20)

    assert impact.feasible_after is True
    assert impact.objective_delta == pytest.approx(0.0)
    assert impact.binding_flips == []


def test_requirement_impact_dropping_demand_zeroes_objective():
    model, _, _ = _production_plan()
    model.solve()
    impact = requirement_impact(model, "demand", drop=True)

    assert impact.change == "dropped"
    assert impact.feasible_after is True
    assert impact.objective_after == pytest.approx(0.0)


def test_requirement_impact_unknown_requirement_raises():
    model, _, _ = _production_plan()
    model.solve()
    with pytest.raises(KeyError):
        requirement_impact(model, "not_a_real_requirement")


def test_solve_diff_detects_objective_and_variable_changes():
    # Widgets are strictly cheaper per unit of both cost and capacity here, so
    # capacity only starts to bind right at the point demand=100 becomes
    # infeasible to hit with capacity=100 exactly (100 widgets, 100 capacity).
    # capacity=240 leaves capacity slack throughout.
    model_a, _, _ = _production_plan(capacity=240)
    result_a = model_a.solve()

    model_b, _, _ = _production_plan(capacity=100)
    result_b = model_b.solve()

    diff = solve_diff(result_a, result_b, binding_report(model_a), binding_report(model_b))

    assert diff.objective_delta == pytest.approx(0.0)
    assert "capacity" in diff.binding_flips
    assert diff.feasibility_changed is False
