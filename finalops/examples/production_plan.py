"""A tiny end-to-end example: extract requirements into a ledger, build a PuLP
model that must cite them, solve, and produce a gated report.

Run with: python examples/production_plan.py
"""

import pulp

from finalops import Ledger, Model, run

BRIEF = """
A factory makes widgets and gadgets.
1. Minimize total production cost. Widgets cost $3/unit, gadgets cost $5/unit.
2. Must produce at least 100 units total to meet demand.
3. The factory can process at most 240 capacity-units; a widget uses 1 unit
   of capacity, a gadget uses 2.
"""


def main() -> None:
    ledger = Ledger()
    ledger.add(id="cost", description="minimize total production cost", source="brief:1", kind="objective")
    ledger.add(id="demand", description="produce at least 100 units total", source="brief:2")
    ledger.add(id="capacity", description="respect the 240 capacity-unit limit", source="brief:3")

    model = Model("production_plan", ledger)
    widgets = pulp.LpVariable("widgets", lowBound=0)
    gadgets = pulp.LpVariable("gadgets", lowBound=0)

    model.set_objective(3 * widgets + 5 * gadgets, requirement_id="cost")
    model.add_constraint(widgets + gadgets >= 100, requirement_id="demand")
    model.add_constraint(widgets + 2 * gadgets <= 240, requirement_id="capacity")

    outcome = run(model, solver="cbc", time_limit=300, max_gap=0.05, out="report.json")

    print(f"passed: {outcome.passed}")
    print(f"status: {outcome.report['status']}")
    print(f"objective: {outcome.report['objective']}")
    print(f"quality_gap: {outcome.report['quality_gap']}")
    if outcome.problems:
        for problem in outcome.problems:
            print(f"  - {problem}")
    print("wrote report.json")


if __name__ == "__main__":
    main()
