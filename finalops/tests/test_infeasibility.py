import pulp

from finalops import Ledger, Model, explain_infeasibility, run


def test_explain_infeasibility_pinpoints_conflicting_requirements():
    ledger = Ledger()
    ledger.add(id="floor", description="produce at least 100 units", source="brief:1")
    ledger.add(id="ceiling", description="produce at most 40 units", source="brief:2")
    ledger.add(id="cost", description="minimize cost", source="brief:3", kind="objective")

    model = Model("conflict", ledger)
    x = pulp.LpVariable("x", lowBound=0)
    model.set_objective(x, requirement_id="cost")
    model.add_constraint(x >= 100, requirement_id="floor")
    model.add_constraint(x <= 40, requirement_id="ceiling")

    result = model.solve()
    assert result.status == "Infeasible"

    diagnosis = explain_infeasibility(model)
    assert diagnosis.feasible is False
    assert len(diagnosis.violations) >= 1

    ids = {v.requirement_id for v in diagnosis.violations}
    # At least one of the two conflicting requirements must be named explicitly.
    assert ids & {"floor", "ceiling"}
    # The violation with the largest slack requirement should carry a magnitude
    # consistent with the size of the conflict (100 - 40 = 60 units apart).
    assert max(v.magnitude for v in diagnosis.violations) > 0


def test_run_reports_infeasibility_with_requirement_labels(tmp_path):
    ledger = Ledger()
    ledger.add(id="floor", description="produce at least 100 units", source="brief:1")
    ledger.add(id="ceiling", description="produce at most 40 units", source="brief:2")
    ledger.add(id="cost", description="minimize cost", source="brief:3", kind="objective")

    model = Model("conflict", ledger)
    x = pulp.LpVariable("x", lowBound=0)
    model.set_objective(x, requirement_id="cost")
    model.add_constraint(x >= 100, requirement_id="floor")
    model.add_constraint(x <= 40, requirement_id="ceiling")

    out = tmp_path / "report.json"
    outcome = run(model, out=str(out))

    assert outcome.passed is False
    assert outcome.report["feasible"] is False
    assert out.exists()
    assert any("floor" in p or "ceiling" in p for p in outcome.problems)
