"""A tiny end-to-end example walking through the four steps a brief gets
decomposed into before any solver code is written: decision variables (with
units), the objective function, the constraints, and the hard data each of
those is built from. Every step registers a ledger requirement and links a
concrete model object (or, for data, a citation) back to it.

Run with: python examples/production_plan.py
"""

import pulp

from finalops import Ledger, Model, run

BRIEF = """
A factory makes widgets and gadgets.
1. Decide how many widgets and how many gadgets to produce per week.
2. Minimize total weekly production cost. Widgets cost $3/unit, gadgets cost $5/unit.
3. Must produce at least 100 units per week total to meet demand.
4. The factory can process at most 240 capacity-units per week; a widget uses
   1 unit of capacity, a gadget uses 2.
"""


def main() -> None:
    ledger = Ledger()

    # 1. Decision variables -- what can be chosen, and in what units.
    ledger.add(
        id="widgets_qty",
        description="widgets to produce per week",
        source="brief:1",
        kind="decision_variable",
        units="units/week",
    )
    ledger.add(
        id="gadgets_qty",
        description="gadgets to produce per week",
        source="brief:1",
        kind="decision_variable",
        units="units/week",
    )

    # 2. Objective function.
    ledger.add(id="cost", description="minimize total weekly production cost", source="brief:2", kind="objective")

    # 3. Constraints.
    ledger.add(id="demand", description="produce at least 100 units per week", source="brief:3")
    ledger.add(id="capacity", description="respect the 240 capacity-unit weekly limit", source="brief:4")

    # 4. Data -- the hard numbers the objective/constraints are built from.
    ledger.add(id="widget_cost", description="cost per widget", source="brief:2", kind="data", units="$/unit")
    ledger.add(id="gadget_cost", description="cost per gadget", source="brief:2", kind="data", units="$/unit")
    ledger.add(
        id="widget_capacity_use", description="capacity used per widget", source="brief:4", kind="data", units="capacity-units/unit"
    )
    ledger.add(
        id="gadget_capacity_use", description="capacity used per gadget", source="brief:4", kind="data", units="capacity-units/unit"
    )

    model = Model("production_plan", ledger)

    widgets = model.add_variable(pulp.LpVariable("widgets", lowBound=0), requirement_id="widgets_qty", units="units/week")
    gadgets = model.add_variable(pulp.LpVariable("gadgets", lowBound=0), requirement_id="gadgets_qty", units="units/week")

    model.cite_data("widget_cost", note="3.0 $/unit, from brief:2")
    model.cite_data("gadget_cost", note="5.0 $/unit, from brief:2")
    model.cite_data("widget_capacity_use", note="1 capacity-unit/unit, from brief:4")
    model.cite_data("gadget_capacity_use", note="2 capacity-units/unit, from brief:4")

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
