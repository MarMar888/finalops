# finalops

AI-native scaffolding for operations-research agents, built on top of [PuLP](https://github.com/coin-or/pulp) rather than instead of it.

The premise: agents (LLMs) are already fluent in PuLP/OR-Tools/Pyomo syntax. What they're bad at is (1) not silently dropping operational rules buried in a brief, and (2) knowing whether a feasible solution is actually any good. `finalops` doesn't add modeling power — it adds cheap, falsifiable checks around the modeling step, on top of plain PuLP.

## Highlights

- **A requirement ledger with four categories** — decision variables, objective, constraints, data — matching how a brief actually gets decomposed into a model. Every rule gets registered with an id, description, and source *before* any model code is written; wiring a variable/constraint/objective/data citation into the model requires citing a ledger id, so a rule that never makes it in shows up as `UNLINKED` instead of disappearing silently. See [The four requirement categories](#the-four-requirement-categories).
- **Full traceability, not just a flag.** Each linked requirement records exactly which constraint (or variable, or data citation) fulfilled it and its expression at link time — `finalops ledger list` and `finalops ledger graph` show the real linkage, not a bare boolean.
- **`run()`: one call, real diagnostics.** Solves, checks feasibility, checks ledger coverage, and checks the quality gap in a single call — against the solver's own internally-computed bound (recovered from the CBC log), not a looser LP-relaxation guess. See [Quickstart](#quickstart).
- **Infeasibility explanation, not just the word "infeasible."** When a model is infeasible, `explain_infeasibility` relaxes every constraint, resolves, and reports which ledger requirements are responsible and by how much — a deletion-free stand-in for an IIS, which the open-source solvers behind PuLP don't provide. See [Explaining an infeasibility](#explaining-an-infeasibility).
- **Sensitivity & what-if analysis.** `binding_report` gives shadow prices per requirement (exact for LPs, tagged with basis for MIPs); `requirement_impact` re-solves after dropping or shifting one requirement's constraint and reports what changed. See [Sensitivity & what-if analysis](#sensitivity--what-if-analysis).
- **A CLI for the whole loop** — `finalops ledger init/add/list/graph` and `finalops check` — so a non-Python agent, a human reviewer, or CI can drive the same ledger and gate on the same report.json a Python script produces.

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

## Explaining an infeasibility

Open-source solvers exposed through PuLP (CBC, HiGHS) don't ship an IIS (irreducible infeasible subsystem) the way some commercial solvers do — when a model is infeasible, you normally just get the word "infeasible" and nothing else. `explain_infeasibility` relaxes every constraint with a penalized slack/surplus, re-solves to minimize total violation, and reports which ledger requirements are responsible and by how much:

```python
import pulp
from finalops import Ledger, Model, explain_infeasibility

ledger = Ledger()
ledger.add(id="floor", description="produce at least 100 units per week", source="brief:1")
ledger.add(id="ceiling", description="produce at most 40 units per week", source="brief:2")
ledger.add(id="cost", description="minimize cost", source="brief:3", kind="objective")

model = Model("conflict", ledger)
x = pulp.LpVariable("x", lowBound=0)
model.set_objective(x, requirement_id="cost")
model.add_constraint(x >= 100, requirement_id="floor")
model.add_constraint(x <= 40, requirement_id="ceiling")
model.solve()

diagnosis = explain_infeasibility(model)
for v in diagnosis.violations:
    print(v.requirement_id, v.description, v.magnitude)
# floor  produce at least 100 units per week  60.0
```

`run()` calls this automatically whenever the solver proves infeasibility, so `outcome.problems` already reads a line like `"infeasible: requirement 'floor' violated by 60"` instead of a bare feasibility flag.

## Sensitivity & what-if analysis

Continuing the `production_plan` model from [Quickstart](#quickstart) (feasible, so there's something to analyze): `binding_report` reports, per requirement, whether its constraint is binding, its slack, and its shadow price — exact for continuous LPs, computed against the LP relaxation (and tagged as such) for MIPs, so an approximate dual is never presented as an exact one:

```python
from finalops import binding_report

report = binding_report(model)
for r in report.requirements:
    print(r.requirement_id, "binding=", r.binding, "shadow_price=", r.shadow_price)
```

`requirement_impact` answers "what if" without hand-editing the model: drop a requirement's constraint entirely, or shift its RHS, re-solve, and see what changed — correct for MIPs too, since it's a real re-solve rather than analytic ranging:

```python
from finalops import requirement_impact

impact = requirement_impact(model, "capacity", rhs_delta=20)
print(impact.objective_delta, impact.binding_flips)
```

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

`finalops ledger graph` renders the same information as a Graphviz DOT graph instead of text — one node per requirement (shaped/colored by kind: decision variables as boxes, the objective as a diamond, constraints as ellipses, data as notes), with an edge from each decision variable to every objective/constraint whose linked expression actually references it. Unlinked requirements are dashed red, so a gap is visible in the picture, not just in `list` output:

```bash
finalops ledger graph ledger.json --out model.dot
dot -Tpng model.dot -o model.png   # if you have Graphviz installed
```

Omit `--out` to print the DOT source to stdout instead.

## Why this shape

Real failure analysis of LLM agents on end-to-end OR tasks (ORAgentBench, 2026) found that ~55% of failures are modeling-side — missed operational rules and brittle formulations — not solver weakness, and that feasibility rates are consistently much higher than pass rates: agents stop at "it runs and satisfies constraints" without checking whether it's close to optimal. `finalops` targets exactly those two gaps rather than competing with existing solver-modeling libraries.

## Status

Early scaffold: PuLP-only backend, CBC solver via PuLP's default. The `Model`/`solve`/`validate` split is intentionally solver-agnostic so additional backends (OR-Tools, HiGHS) can be added later without changing the ledger or CLI surface.
