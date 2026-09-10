# finalops

AI-native scaffolding for operations-research agents, built on top of [PuLP](https://github.com/coin-or/pulp) rather than instead of it.

The premise: agents (LLMs) are already fluent in PuLP/OR-Tools/Pyomo syntax. What they're bad at is (1) not silently dropping operational rules buried in a brief, and (2) knowing whether a feasible solution is actually any good. `finalops` doesn't add modeling power — it adds two cheap, falsifiable checks around the modeling step:

1. **A requirement ledger.** Every rule pulled from the brief gets registered — id, description, and where it came from — *before* any model code is written. Constraints wired into the model must cite a ledger id, so a rule that never makes it into the formulation shows up as an `UNLINKED` entry instead of disappearing silently.
2. **A live feasibility + quality-gap oracle.** After solving, `check_feasibility` recomputes every constraint against the current solution (structured violations, not "trust the code"), and `quality_gap` compares the objective against an LP-relaxation bound so "it ran and is feasible" and "it's actually good" stop being indistinguishable.

## Quickstart

```python
import pulp
from finalops import Ledger, Model, run

ledger = Ledger()
ledger.add(id="demand", description="meet demand for every product", source="brief.md:3")
ledger.add(id="capacity", description="can't exceed factory capacity", source="brief.md:5")
ledger.add(id="cost", description="minimize total production cost", source="brief.md:1", kind="objective")

model = Model("production_plan", ledger)

x = pulp.LpVariable("widgets", lowBound=0)
y = pulp.LpVariable("gadgets", lowBound=0)

model.set_objective(3 * x + 5 * y, requirement_id="cost")
model.add_constraint(x + y >= 100, requirement_id="demand")
model.add_constraint(x + 2 * y <= 240, requirement_id="capacity")

outcome = run(model, solver="cbc", time_limit=300, max_gap=0.05, out="report.json")
print(outcome.passed, outcome.problems)
```

`run()` is the one call an agent needs after the model is built and tagged: it solves, checks feasibility, checks ledger coverage, checks the quality gap, and returns a single `RunResult(passed, report, problems)` — instead of chaining solve → build_report → check as three separate steps an agent could stop short of. `outcome.problems` is a plain list of human-readable strings ("infeasible: 2 constraint(s) violated", "1 ledger requirement(s) never linked...") the agent can read and act on directly.

If you'd rather gate from the shell (CI, a non-Python agent) instead of Python:

```bash
finalops check report.json --max-gap 0.05
```

`check` reads the `report.json` that `run()` already wrote and exits non-zero with the same diagnostics if anything's wrong.

## The four requirement categories

Every ledger requirement has a `kind`, matching the order a brief actually gets
decomposed into a model:

1. **`decision_variable`** — what can be chosen. Register it with `ledger.add(..., kind="decision_variable", units="hours/week")`, then link it to the real PuLP variable with `model.add_variable(var, requirement_id=..., units=...)`. Units are stored explicitly — PuLP variables have none of their own, and a dropped or mismatched unit is exactly the kind of silent error the ledger exists to catch.
2. **`objective`** — what "good" means. Linked via `model.set_objective(...)`.
3. **`constraint`** — what's not allowed, logical (e.g. can't produce a negative quantity) or specific to the brief. Linked via `model.add_constraint(...)`.
4. **`data`** — the hard numbers everything above is built from (a bound, a cost coefficient). Data has no PuLP object to attach to, so it's linked with an explicit citation: `model.cite_data(requirement_id, note="3.0 $/unit, from data/costs.csv")`.

`finalops ledger list` shows the units and the linked object for each:

```
[linked  ] widgets_qty (decision_variable): widgets to produce per week  <- brief:1 [units: units/week]
           -> widgets: Continuous variable, bounds=[0, +inf], units=units/week
[linked  ] widget_cost (data): cost per widget  <- brief:2 [units: dollars/unit]
           -> data: 3.0 dollars/unit, from brief:2
```

See `examples/production_plan.py` for a full walkthrough using all four.

## Managing the ledger from the CLI

```bash
finalops ledger init ledger.json
finalops ledger add ledger.json --id demand --description "meet demand for every product" --source "brief.md:3"
finalops ledger list ledger.json
```

`ledger list` shows, per requirement, which constraint(s) (or the objective) fulfilled it and their actual expression at link time — not just a linked/unlinked flag:

```
[linked  ] demand (constraint): meet demand for every product  <- brief.md:3
           -> c1: widgets + gadgets >= 100
```

A requirement can be linked to more than one constraint (`linked_constraints` is a list); an unlinked one shows no `->` lines at all.

## Why this shape

Real failure analysis of LLM agents on end-to-end OR tasks (ORAgentBench, 2026) found that ~55% of failures are modeling-side — missed operational rules and brittle formulations — not solver weakness, and that feasibility rates are consistently much higher than pass rates: agents stop at "it runs and satisfies constraints" without checking whether it's close to optimal. `finalops` targets exactly those two gaps rather than competing with existing solver-modeling libraries.

## Status

Early scaffold: PuLP-only backend, CBC solver via PuLP's default. The `Model`/`solve`/`validate` split is intentionally solver-agnostic so additional backends (OR-Tools, HiGHS) can be added later without changing the ledger or CLI surface.
