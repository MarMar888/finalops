import pulp
import pytest

from finalops import Ledger, Model
from finalops.validate import check_feasibility, quality_gap


def _solved_lp():
    ledger = Ledger()
    ledger.add(id="demand", description="meet demand", source="brief.md:3")
    ledger.add(id="capacity", description="respect capacity", source="brief.md:5")
    ledger.add(id="cost", description="minimize cost", source="brief.md:1", kind="objective")

    model = Model("m", ledger)
    x = pulp.LpVariable("x", lowBound=0)
    y = pulp.LpVariable("y", lowBound=0)
    model.set_objective(3 * x + 5 * y, requirement_id="cost")
    model.add_constraint(x + y >= 100, requirement_id="demand")
    model.add_constraint(x + 2 * y <= 240, requirement_id="capacity")
    return model, x, y


def test_check_feasibility_on_optimal_solution():
    model, _, _ = _solved_lp()
    result = model.solve()
    report = check_feasibility(model)
    assert report.feasible is True
    assert report.violations == []
    assert result.status == "Optimal"


def test_check_feasibility_detects_violation():
    model, x, y = _solved_lp()
    model.solve()
    # Force the demand constraint to be violated by overriding the solved values.
    x.varValue = 10
    y.varValue = 10
    report = check_feasibility(model)
    assert report.feasible is False
    assert len(report.violations) >= 1
    assert all(v.slack < 0 for v in report.violations)


def test_quality_gap_pure_lp_is_near_zero():
    model, _, _ = _solved_lp()
    result = model.solve()
    gap = quality_gap(model, result.objective)
    # This LP has no integer variables, so the relaxation bound equals the
    # optimal objective and the gap should be ~0.
    assert gap == pytest.approx(0.0, abs=1e-6)


def test_quality_gap_none_without_objective():
    model, _, _ = _solved_lp()
    assert quality_gap(model, None) is None
