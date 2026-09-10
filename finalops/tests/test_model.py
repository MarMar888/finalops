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


def test_add_variable_requires_known_id():
    model = Model("m", _ledger())
    with pytest.raises(UntaggedConstraintError):
        model.add_variable(pulp.LpVariable("x", lowBound=0), requirement_id="not_in_ledger")


def test_add_variable_marks_ledger_linked_and_records_units():
    ledger = Ledger()
    ledger.add(id="x_qty", description="x to produce per week", source="brief:1", kind="decision_variable")

    model = Model("m", ledger)
    model.add_variable(pulp.LpVariable("x", lowBound=0), requirement_id="x_qty", units="units/week")

    req = ledger.get("x_qty")
    assert req.linked is True
    assert model.requirement_by_variable["x"] == "x_qty"
    assert "units/week" in req.linked_constraints[0].expression


def test_cite_data_requires_known_id():
    model = Model("m", _ledger())
    with pytest.raises(UntaggedConstraintError):
        model.cite_data("not_in_ledger", note="3.0 $/unit")


def test_cite_data_marks_ledger_linked():
    ledger = Ledger()
    ledger.add(id="unit_cost", description="cost per unit", source="brief:2", kind="data", units="$/unit")

    model = Model("m", ledger)
    model.cite_data("unit_cost", note="3.0 $/unit, from brief:2")

    req = ledger.get("unit_cost")
    assert req.linked is True
    assert req.linked_constraints[0].expression == "3.0 $/unit, from brief:2"


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
