"""Extends the production_plan example to exercise the new sensitivity
module: binding report, a what-if on the capacity constraint, and a
before/after solve diff.

Run with: python examples/sensitivity_demo.py
"""

import pulp

from finalops import Ledger, Model, binding_report, requirement_impact, solve_diff


def build_model() -> Model:
    ledger = Ledger()
    ledger.add(id="cost", description="minimize total production cost", source="brief:1", kind="objective")
    ledger.add(id="demand", description="produce at least 100 units total", source="brief:2")
    ledger.add(id="capacity", description="respect the 240 capacity-unit limit", source="brief:3")

    model = Model("production_plan", ledger)
    widgets = pulp.LpVariable("widgets", lowBound=0)
    gadgets = pulp.LpVariable("gadgets", lowBound=0)

    model.set_objective(3 * widgets + 5 * gadgets, requirement_id="cost")
    model.add_constraint(widgets + gadgets >= 100, requirement_id="demand", name="demand")
    model.add_constraint(widgets + 2 * gadgets <= 240, requirement_id="capacity", name="capacity")
    return model


def main() -> None:
    model = build_model()
    before_result = model.solve()
    print(f"objective: {before_result.objective}")

    print("\n--- binding report ---")
    report = binding_report(model)
    print(f"basis: {report.basis}")
    for r in report.requirements:
        print(f"  {r.requirement_id:10s} binding={r.binding!s:5s} slack={r.slack:8.2f} shadow_price={r.shadow_price}")

    print("\n--- what-if: relax capacity by 20 units ---")
    impact = requirement_impact(model, "capacity", rhs_delta=20)
    print(f"  objective before: {impact.objective_before}")
    print(f"  objective after:  {impact.objective_after}")
    print(f"  objective delta:  {impact.objective_delta}")
    print(f"  binding flips:    {impact.binding_flips}")

    print("\n--- what-if: drop demand entirely ---")
    impact2 = requirement_impact(model, "demand", drop=True)
    print(f"  objective before: {impact2.objective_before}")
    print(f"  objective after:  {impact2.objective_after}")
    print(f"  binding flips:    {impact2.binding_flips}")

    print("\n--- solve diff: original vs. capacity raised to 300 ---")
    widgets2 = pulp.LpVariable("widgets", lowBound=0)
    gadgets2 = pulp.LpVariable("gadgets", lowBound=0)
    ledger2 = Ledger()
    ledger2.add(id="cost", description="minimize total production cost", source="brief:1", kind="objective")
    ledger2.add(id="demand", description="produce at least 100 units total", source="brief:2")
    ledger2.add(id="capacity", description="respect the 300 capacity-unit limit", source="brief:3 (revised)")
    model2 = Model("production_plan_v2", ledger2)
    model2.set_objective(3 * widgets2 + 5 * gadgets2, requirement_id="cost")
    model2.add_constraint(widgets2 + gadgets2 >= 100, requirement_id="demand", name="demand")
    model2.add_constraint(widgets2 + 2 * gadgets2 <= 300, requirement_id="capacity", name="capacity")
    after_result = model2.solve()

    diff = solve_diff(before_result, after_result, binding_report(model), binding_report(model2))
    print(f"  objective delta: {diff.objective_delta}")
    print(f"  variable deltas: {diff.variable_deltas}")
    print(f"  binding flips:   {diff.binding_flips}")
    print(f"  feasibility changed: {diff.feasibility_changed}")


if __name__ == "__main__":
    main()
