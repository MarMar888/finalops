import pulp
import pytest

from finalops import Ledger, Model, UntaggedConstraintError


def _ledger():
    ledger = Ledger()
    ledger.add(id="demand", description="meet demand", source="brief.md:3")
    ledger.add(id="capacity", description="respect capacity", source="brief.md:5")
    ledger.add(id="cost", description="minimize cost", source="brief.md:1", kind="objective")
    return ledger


def test_add_constraint_requires_known_id():
    model = Model("m", _ledger())
    x = pulp.LpVariable("x", lowBound=0)
    with pytest.raises(UntaggedConstraintError):
        model.add_constraint(x >= 1, requirement_id="not_in_ledger")


def test_add_constraint_marks_ledger_linked():
    ledger = _ledger()
    model = Model("m", ledger)
    x = pulp.LpVariable("x", lowBound=0)
    model.add_constraint(x >= 1, requirement_id="demand")
    assert ledger.get("demand").linked is True
    assert [r.id for r in ledger.unlinked()] == ["capacity", "cost"]


def test_set_objective_requires_known_id():
    model = Model("m", _ledger())
    x = pulp.LpVariable("x", lowBound=0)
    with pytest.raises(UntaggedConstraintError):
        model.set_objective(3 * x, requirement_id="not_in_ledger")


def test_solve_simple_lp():
    ledger = _ledger()
    model = Model("m", ledger)
    x = pulp.LpVariable("x", lowBound=0)
    y = pulp.LpVariable("y", lowBound=0)

    model.set_objective(3 * x + 5 * y, requirement_id="cost")
    model.add_constraint(x + y >= 100, requirement_id="demand")
    model.add_constraint(x + 2 * y <= 240, requirement_id="capacity")

    result = model.solve()
    assert result.status == "Optimal"
    assert result.objective == pytest.approx(300.0)
    assert len(ledger.unlinked()) == 0
