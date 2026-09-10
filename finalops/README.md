# finalops

Ask an LLM to write you a PuLP model and it will. It knows the syntax cold — variables, constraints, the objective, all of it. What it's bad at is two much quieter things: forgetting a rule that was sitting right there in the brief, and not knowing whether the number it eventually prints is any good.

Those are the two places these things actually break. Not the code. The code always looks fine. What breaks is upstream of the code (a rule nobody wrote down gets left out) or downstream of it (a feasible answer gets mistaken for a good one). So that's what `finalops` is for. It doesn't add modeling power — [PuLP](https://github.com/coin-or/pulp) already has plenty. It adds a handful of cheap, mechanical checks around the modeling step, the kind a careful person does by hand and an agent, left to itself, usually skips.

## What it actually does

Before you write a line of model code, you write down every requirement you can find in the brief. Not as prose — as a ledger entry, with an id, a description, and where it came from. There are four kinds of requirement, because a formulation only ever decomposes into four things: what can be chosen, what "good" means, what's not allowed, and the hard numbers everything else is built from.

Then you build the model. Every variable, every constraint, the objective, even a bare number pulled from a data file, has to point back to one of those ledger entries. There's no way to wire something into the model without saying which requirement it satisfies. And if a requirement you wrote down never gets pointed to by anything — that shows up plainly, as `UNLINKED`, instead of just quietly not being there.

Once you solve, you get more than an objective value. `run()` checks feasibility, checks that every requirement actually got used, and checks how far your answer is from a real bound — not a rough LP-relaxation guess, but the bound the solver itself computed internally and would otherwise have thrown away. If the model comes back infeasible, you don't just get told "infeasible" and left to guess. It relaxes every constraint, resolves, and tells you which requirements are actually in conflict, and by how much. And if you want to know what a constraint is costing you, you can ask for its shadow price, or just tell it to loosen that constraint and re-solve, and see what changes.

None of this is clever. It's the stuff a careful modeler does anyway. The only idea here is to make an agent do it too, by making the shortcuts unavailable rather than just discouraged.

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

`run()` is the one call you need once the model is built and tagged. It solves, checks feasibility, checks ledger coverage, checks the quality gap, and hands back a single `RunResult(passed, report, problems)` — instead of making you chain solve → build_report → check as three separate steps you could stop short of. `outcome.problems` is just a list of plain strings ("infeasible: 2 constraint(s) violated", "1 ledger requirement(s) never linked...") you can read directly, or have an agent read directly.

If you'd rather gate from the shell — CI, or an agent that isn't Python — instead of from inside the script:

```bash
finalops check report.json --max-gap 0.05
```

`check` reads the `report.json` that `run()` already wrote and exits non-zero with the same diagnostics if anything's wrong.

## The four requirement categories

Every ledger requirement has a `kind`, in the order a brief actually gets worked through:

1. **`decision_variable`** — what can be chosen. Register it with `ledger.add(..., kind="decision_variable", units="hours/week")`, then link it to the real PuLP variable with `model.add_variable(var, requirement_id=..., units=...)`. Units get stored explicitly, because PuLP variables don't have any of their own, and a dropped or mismatched unit is exactly the kind of thing that slips past everyone until it doesn't.
2. **`objective`** — what "good" means. Linked via `model.set_objective(...)`.
3. **`constraint`** — what's not allowed, logical (you can't work a negative number of hours) or specific to the brief. Linked via `model.add_constraint(...)`.
4. **`data`** — the hard numbers everything above is built from: a bound, a cost coefficient. Data has no PuLP object to attach to, so you link it with a plain citation: `model.cite_data(requirement_id, note="3.0 $/unit, from data/costs.csv")`.

`finalops ledger list` shows the units and the linked object for each:

```
[linked  ] widgets_qty (decision_variable): widgets to produce per week  <- brief:1 [units: units/week]
           -> widgets: Continuous variable, bounds=[0, +inf], units=units/week
[linked  ] widget_cost (data): cost per widget  <- brief:2 [units: dollars/unit]
           -> data: 3.0 dollars/unit, from brief:2
```

See `examples/production_plan.py` for a full walkthrough using all four.

## Explaining an infeasibility

The open-source solvers behind PuLP — CBC, HiGHS — don't ship anything like the IIS (irreducible infeasible subsystem) that some commercial solvers do. When a model is infeasible, you normally get the word "infeasible" and nothing else. That's not much to work with.

`explain_infeasibility` relaxes every constraint with a penalized slack, re-solves to minimize total violation, and tells you which ledger requirements are responsible, and by how much:

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

`run()` calls this automatically whenever the solver proves infeasibility, so `outcome.problems` already reads a line like `"infeasible: requirement 'floor' violated by 60"` instead of a bare flag.

## Sensitivity & what-if analysis

Continuing the `production_plan` model from [Quickstart](#quickstart) — it's feasible, so there's something to analyze. `binding_report` tells you, per requirement, whether its constraint is binding, how much slack it has, and its shadow price. Exact for continuous LPs; for MIPs it's computed against the LP relaxation, and tagged as such, so an approximate dual never gets presented as an exact one:

```python
from finalops import binding_report

report = binding_report(model)
for r in report.requirements:
    print(r.requirement_id, "binding=", r.binding, "shadow_price=", r.shadow_price)
```

`requirement_impact` answers "what if" without you having to hand-edit the model: drop a requirement's constraint entirely, or shift its bound, re-solve, and see what actually changed. It's a real re-solve, not analytic ranging, so it's correct for MIPs too:

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

(Once a `ledger.json` exists in your working directory, you can drop the path — every ledger subcommand defaults to it.)

`ledger list` shows, per requirement, which constraint (or the objective) fulfilled it and its actual expression at link time — not just a linked/unlinked flag:

```
[linked  ] demand (constraint): meet demand for every product  <- brief.md:3
           -> c1: widgets + gadgets >= 100
```

A requirement can be linked to more than one constraint; an unlinked one shows no `->` lines at all.

`finalops ledger graph` draws the same thing instead of printing it: one node per requirement, shaped and colored by kind, with an edge from each decision variable to every objective/constraint whose linked expression actually references it. Unlinked requirements are dashed red, so a gap is something you can see, not just something you can grep for:

```bash
finalops ledger graph ledger.json --out model.dot
dot -Tpng model.dot -o model.png   # if you have Graphviz installed
```

Leave off `--out` and it prints the DOT source to stdout instead.

## Why it's built this way

There's a benchmark called ORAgentBench that tested fourteen frontier agent setups on realistic, end-to-end operations-research tasks. The best of them passed 35.5% of the tasks. And the failures weren't mostly about solvers running out of time or code not running — about 55% of them were modeling-side: a rule got missed, or the formulation was brittle in a way that only showed up on the real data. Feasibility rates were also consistently higher than pass rates, meaning agents would happily hand back an answer that satisfied every constraint and just wasn't very good, without ever checking.

That matches what you'd expect if you think about it for a minute. Writing correct PuLP syntax is a narrow, well-covered skill — it's exactly the kind of thing these models have seen a million times. Noticing that a footnote in a CSV file changes a constraint, or noticing that your feasible answer is 40% off the true optimum, isn't a syntax problem. There's no compiler error for it. So `finalops` doesn't try to make the modeling smarter. It tries to make the two failure modes visible, cheaply, before you've shipped the answer.

## Status

Early. PuLP-only, CBC as the solver, via PuLP's default. The way `Model`, `solve`, and `validate` are split apart is deliberately solver-agnostic, so other backends — OR-Tools, HiGHS — can be added later without touching the ledger or the CLI.
