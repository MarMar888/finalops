"""Generate the sample bundles the frontend debugger ships with.

Each scenario is a small model in a different state a debugger has to explain:
a healthy LP (written as ledger calls), an infeasible conflict, an unbounded model, and a MIP with a rule that
never made it into the model.

Run with: python examples/generate_debug_samples.py [output_dir]
Default output is ../public/samples (the Next.js app's public folder).
"""

import sys
from pathlib import Path

import pulp

from finalops import CapacityLimit, DemandCoverage, Ledger, Model, build_debug_bundle


def production_plan() -> Model:
    ledger = Ledger()
    ledger.variable("widgets", units="units/week", source="brief:1")
    ledger.variable("gadgets", units="units/week", source="brief:1")
    ledger.data("widget_cost", 3, units="$/unit", source="brief:2")
    ledger.data("gadget_cost", 5, units="$/unit", source="brief:2")
    ledger.minimize("cost", {"widgets": "widget_cost", "gadgets": "gadget_cost"}, description="minimize total weekly production cost", source="brief:2")
    ledger.constrain(DemandCoverage(id="demand", description="produce at least 100 units per week", required=100, covered_by=["widgets", "gadgets"], source="brief:3"))
    ledger.constrain(CapacityLimit(id="capacity", description="respect the 240 capacity-unit weekly limit", limit=240, uses={"widgets": 1, "gadgets": 2}, source="brief:4"))
    return Model.from_ledger(ledger, name="production_plan")


def infeasible_bakery() -> Model:
    ledger = Ledger()
    ledger.add(id="bread_qty", description="loaves of bread baked per day", source="brief:1", kind="decision_variable", units="loaves/day")
    ledger.add(id="cake_qty", description="cakes baked per day", source="brief:1", kind="decision_variable", units="cakes/day")
    ledger.add(id="profit", description="maximize daily profit", source="brief:2", kind="objective")
    ledger.add(id="contract_bread", description="contract requires at least 60 loaves/day", source="brief:3")
    ledger.add(id="contract_cakes", description="contract requires at least 30 cakes/day", source="brief:3")
    ledger.add(id="oven_hours", description="oven runs at most 100 hours/day (bread 1h, cake 2h)", source="brief:4")
    ledger.add(id="labor_hours", description="at most 200 labor hours/day (bread 1.5h, cake 1h)", source="brief:5")

    model = Model("infeasible_bakery", ledger, sense=pulp.LpMaximize)
    bread = model.add_variable(pulp.LpVariable("bread", lowBound=0), requirement_id="bread_qty", units="loaves/day")
    cakes = model.add_variable(pulp.LpVariable("cakes", lowBound=0), requirement_id="cake_qty", units="cakes/day")
    model.set_objective(2 * bread + 5 * cakes, requirement_id="profit")
    model.add_constraint(bread >= 60, requirement_id="contract_bread")
    model.add_constraint(cakes >= 30, requirement_id="contract_cakes")
    model.add_constraint(bread + 2 * cakes <= 100, requirement_id="oven_hours")
    model.add_constraint(1.5 * bread + cakes <= 200, requirement_id="labor_hours")
    return model


def unbounded_missing_limit() -> Model:
    ledger = Ledger()
    ledger.add(id="units_qty", description="units to sell per week", source="brief:1", kind="decision_variable", units="units/week")
    ledger.add(id="profit", description="maximize weekly profit", source="brief:2", kind="objective")
    ledger.add(id="min_order", description="must sell at least 10 units to keep the account", source="brief:3")
    ledger.add(id="supply_limit", description="supplier can deliver at most 500 units/week", source="brief:4")

    model = Model("unbounded_missing_limit", ledger, sense=pulp.LpMaximize)
    units = model.add_variable(pulp.LpVariable("units", lowBound=0), requirement_id="units_qty", units="units/week")
    model.set_objective(4 * units, requirement_id="profit")
    model.add_constraint(units >= 10, requirement_id="min_order")
    # supply_limit is in the ledger but was never wired into the model -- the classic cause.
    return model


def knapsack_mip() -> Model:
    ledger = Ledger()
    ledger.add(id="pick", description="which items to load (0/1 each)", source="brief:1", kind="decision_variable", units="0/1")
    ledger.add(id="value", description="maximize total value loaded", source="brief:2", kind="objective")
    ledger.add(id="weight_cap", description="total weight at most 15 kg", source="brief:3")
    ledger.add(id="volume_cap", description="total volume at most 10 L", source="brief:3")
    ledger.add(id="keep_perishable", description="at least one perishable item must be loaded", source="brief:4")

    items = {"tent": (6, 5, 12), "stove": (4, 3, 9), "water": (5, 6, 8), "rope": (2, 1, 4), "camera": (1, 2, 7), "books": (3, 4, 5)}
    model = Model("knapsack_mip", ledger, sense=pulp.LpMaximize)
    picks = {
        name: model.add_variable(pulp.LpVariable(name, cat="Binary"), requirement_id="pick", units="0/1")
        for name in items
    }
    model.set_objective(pulp.lpSum(v * picks[n] for n, (_, _, v) in items.items()), requirement_id="value")
    model.add_constraint(pulp.lpSum(w * picks[n] for n, (w, _, _) in items.items()) <= 15, requirement_id="weight_cap")
    model.add_constraint(pulp.lpSum(vol * picks[n] for n, (_, vol, _) in items.items()) <= 10, requirement_id="volume_cap")
    # keep_perishable is never wired in: it stays UNLINKED so the debugger can show it.
    return model


SCENARIOS = {
    "production-plan": production_plan,
    "infeasible-bakery": infeasible_bakery,
    "unbounded-missing-limit": unbounded_missing_limit,
    "knapsack-mip": knapsack_mip,
}


def main() -> None:
    default_out = Path(__file__).resolve().parents[2] / "public" / "samples"
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else default_out
    out_dir.mkdir(parents=True, exist_ok=True)

    for name, build in SCENARIOS.items():
        bundle = build_debug_bundle(build(), out=out_dir / f"{name}.json")
        print(f"{name:26} status={bundle['summary']['status']:11} problems={len(bundle['summary']['problems'])}")

    print(f"wrote {len(SCENARIOS)} bundles to {out_dir}")


if __name__ == "__main__":
    main()
