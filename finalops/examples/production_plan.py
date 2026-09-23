"""The same production plan, written only as ledger calls: no PuLP, no model object.

Each call records a requirement from the brief (what it says, where it came from, its
units) together with its math, and `run` builds and solves the model from the ledger.
Compare with the raw-PuLP version in the README's "Dropping down to PuLP" section.

Run with: python examples/production_plan.py
"""

from finalops import CapacityLimit, DemandCoverage, Ledger, run

BRIEF = """
A factory makes widgets and gadgets.
1. Minimize total weekly production cost. Widgets cost $3/unit, gadgets cost $5/unit.
2. Decide how many widgets and how many gadgets to produce per week.
3. Must produce at least 100 units per week total to meet demand.
4. The factory can process at most 240 capacity-units per week; a widget uses
   1 unit of capacity, a gadget uses 2.
"""


def main() -> None:
    ledger = Ledger()

    # What can be chosen
    ledger.variable("widgets", units="units/week", source="brief:2")
    ledger.variable("gadgets", units="units/week", source="brief:2")

    # The hard numbers, kept with their units and where they came from
    ledger.data("widget_cost", 3, units="$/unit", source="brief:1")
    ledger.data("gadget_cost", 5, units="$/unit", source="brief:1")
    ledger.data("widget_capacity_use", 1, units="capacity-units/unit", source="brief:4")
    ledger.data("gadget_capacity_use", 2, units="capacity-units/unit", source="brief:4")

    # What "good" means
    ledger.minimize("cost", {"widgets": "widget_cost", "gadgets": "gadget_cost"}, source="brief:1")

    # What's not allowed
    ledger.constrain(
        DemandCoverage(
            id="demand",
            description="produce at least 100 units per week",
            required=100,
            covered_by=["widgets", "gadgets"],
            source="brief:3",
        )
    )
    ledger.constrain(
        CapacityLimit(
            id="capacity",
            description="respect the 240 capacity-unit weekly limit",
            limit=240,
            uses={"widgets": "widget_capacity_use", "gadgets": "gadget_capacity_use"},
            source="brief:4",
        )
    )

    outcome = run(ledger, name="production_plan", out="report.json")

    print(f"passed: {outcome.passed}")
    print(f"status: {outcome.report['status']}")
    print(f"objective: {outcome.report['objective']}")
    print(f"quality_gap: {outcome.report['quality_gap']}")
    print(f"rule_violations: {outcome.report['rule_violations']}")
    for problem in outcome.problems:
        print(f"  - {problem}")
    print("wrote report.json")

    ledger.to_json("ledger.json")
    print("wrote ledger.json (the specs and the links, so `finalops ledger list` can show them)")


if __name__ == "__main__":
    main()
