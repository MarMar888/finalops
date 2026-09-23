import pulp

from finalops import Ledger, Model, explain_infeasibility, find_conflict, run


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


# -- the minimal conflict set -----------------------------------------------------


def _bakery() -> Model:
    ledger = Ledger()
    ledger.add(id="profit", description="maximize daily profit", source="brief:1", kind="objective")
    ledger.add(id="contract_bread", description="at least 60 loaves/day", source="brief:2")
    ledger.add(id="contract_cakes", description="at least 30 cakes/day", source="brief:2")
    ledger.add(id="oven_hours", description="oven runs at most 100 hours/day", source="brief:3")
    ledger.add(id="labor_hours", description="at most 200 labor hours/day", source="brief:4")

    model = Model("bakery", ledger, sense=pulp.LpMaximize)
    bread = pulp.LpVariable("bread", lowBound=0)
    cakes = pulp.LpVariable("cakes", lowBound=0)
    model.set_objective(2 * bread + 5 * cakes, requirement_id="profit")
    model.add_constraint(bread >= 60, requirement_id="contract_bread")
    model.add_constraint(cakes >= 30, requirement_id="contract_cakes")
    model.add_constraint(bread + 2 * cakes <= 100, requirement_id="oven_hours")
    model.add_constraint(1.5 * bread + cakes <= 200, requirement_id="labor_hours")
    return model


def _feasible_without(model: Model, dropped: str) -> bool:
    """Independent check: solve only the constraints other than `dropped`."""
    trial = pulp.LpProblem("check", pulp.LpMinimize)
    for name, constraint in model.problem.constraints.items():
        if name != dropped:
            trial.addConstraint(constraint.copy(), name)
    trial.solve(pulp.PULP_CBC_CMD(msg=False))
    return pulp.LpStatus[trial.status] != "Infeasible"


def test_conflict_names_every_rule_that_has_to_collide_and_only_those():
    model = _bakery()
    diagnosis = explain_infeasibility(model)

    conflict = diagnosis.conflict
    assert conflict is not None and conflict.minimal
    # 60 loaves + 30 cakes need 120 oven hours; the oven has 100. Labor is a bystander.
    assert set(conflict.requirement_ids) == {"contract_bread", "contract_cakes", "oven_hours"}
    assert all(m.kind == "constraint" for m in conflict.members)
    # The elastic relaxation alone would have named just one of them; the conflict is the whole story.
    assert len(diagnosis.violations) < len(conflict.members)


def test_removing_any_member_of_the_conflict_makes_the_rest_satisfiable():
    model = _bakery()
    conflict = explain_infeasibility(model).conflict

    labor = next(n for n, r in model.requirement_by_constraint.items() if r == "labor_hours")
    assert not _feasible_without(model, dropped=labor)  # a bystander: dropping it fixes nothing
    for member in conflict.members:
        assert _feasible_without(model, dropped=member.name), member.name


def test_a_variable_bound_can_be_part_of_the_conflict():
    ledger = Ledger()
    ledger.add(id="x_qty", description="units to make", source="brief:1", kind="decision_variable")
    ledger.add(id="need", description="make at least 10 units", source="brief:2")
    ledger.add(id="cost", description="minimize units", source="brief:3", kind="objective")
    model = Model("bound_conflict", ledger)
    x = model.add_variable(pulp.LpVariable("x", lowBound=0, upBound=5), requirement_id="x_qty")
    model.set_objective(x, requirement_id="cost")
    model.add_constraint(x >= 10, requirement_id="need")

    conflict = explain_infeasibility(model).conflict

    kinds = {(m.kind, m.bound) for m in conflict.members}
    assert kinds == {("bound", "upper"), ("constraint", None)}  # the default x >= 0 is not blamed
    upper = next(m for m in conflict.members if m.kind == "bound")
    assert (upper.requirement_id, upper.expression) == ("x_qty", "x <= 5")


def test_a_conflict_caused_by_integrality_is_found():
    ledger = Ledger()
    ledger.add(id="half", description="exactly 1.5 crates", source="brief:1")
    ledger.add(id="cost", description="minimize crates", source="brief:2", kind="objective")
    model = Model("integer_conflict", ledger)
    x = pulp.LpVariable("x", lowBound=0, cat="Integer")
    model.set_objective(x, requirement_id="cost")
    model.add_constraint(2 * x == 3, requirement_id="half")

    assert model.solve().status == "Infeasible"
    conflict = explain_infeasibility(model).conflict
    assert conflict.requirement_ids == ["half"]


def test_find_conflict_returns_none_for_a_feasible_model():
    ledger = Ledger()
    ledger.add(id="cost", description="minimize x", source="brief:1", kind="objective")
    ledger.add(id="floor", description="at least 3", source="brief:2")
    model = Model("fine", ledger)
    x = pulp.LpVariable("x", lowBound=0)
    model.set_objective(x, requirement_id="cost")
    model.add_constraint(x >= 3, requirement_id="floor")
    assert find_conflict(model) is None


def test_running_out_of_solves_returns_a_real_but_unproven_conflict():
    model = _bakery()
    conflict = find_conflict(model, max_solves=2)
    assert conflict is not None and conflict.minimal is False
    assert conflict.solves <= 2
    # Still a genuine infeasible subset: everything in it can't hold together.
    kept = {m.name for m in conflict.members if m.kind == "constraint"}
    trial = pulp.LpProblem("check", pulp.LpMinimize)
    for name, constraint in model.problem.constraints.items():
        if name in kept:
            trial.addConstraint(constraint.copy(), name)
    trial.solve(pulp.PULP_CBC_CMD(msg=False))
    assert pulp.LpStatus[trial.status] == "Infeasible"


def test_the_report_and_problems_lead_with_the_conflict(tmp_path):
    outcome = run(_bakery(), out=tmp_path / "report.json")

    assert outcome.passed is False
    assert outcome.report["conflict"]["requirement_ids"] == ["contract_bread", "contract_cakes", "oven_hours"]
    first = outcome.problems[0]
    assert first.startswith("infeasible: these cannot all hold together")
    assert "'contract_bread' (at least 60 loaves/day)" in first and "'oven_hours'" in first
    assert "labor_hours" not in first
