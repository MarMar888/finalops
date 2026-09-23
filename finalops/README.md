# finalops

Ask an LLM to write you a PuLP model and it will. It knows the syntax cold — variables, constraints, the objective, all of it. What it's bad at is two much quieter things: forgetting a rule that was sitting right there in the brief, and not knowing whether the number it eventually prints is any good.

Those are the two places these things actually break. Not the code. The code always looks fine. What breaks is upstream of the code (a rule nobody wrote down gets left out) or downstream of it (a feasible answer gets mistaken for a good one). So that's what `finalops` is for. It doesn't add modeling power — [PuLP](https://github.com/coin-or/pulp) already has plenty. It adds a handful of cheap, mechanical checks around the modeling step, the kind a careful person does by hand and an agent, left to itself, usually skips.

## What it actually does

Before you write a line of model code, you write down every requirement you can find in the brief. Not as prose — as a ledger entry, with an id, a description, and where it came from. There are four kinds of requirement, because a formulation only ever decomposes into four things: what can be chosen, what "good" means, what's not allowed, and the hard numbers everything else is built from.

And you say what each one *is* in the same breath. A rule isn't a sentence you later translate into PuLP. It's an object: `CapacityLimit(limit=240, uses={"widgets": 1, "gadgets": 2}, source="brief:5")`. That one object carries both what the brief said and the math, so the two can't drift apart, and `finalops` builds the PuLP model from the ledger itself. You never write a constraint. And if a requirement you wrote down never gets defined, that shows up plainly, as `UNLINKED`, instead of just quietly not being there.

Once you solve, you get more than an objective value. `run()` checks feasibility, checks that every requirement actually got used, tests the answer against each rule a second time in the rule's own terms, and checks how far your answer is from a real bound — not a rough LP-relaxation guess, but the bound the solver itself computed internally and would otherwise have thrown away. If the model comes back infeasible, you don't just get told "infeasible" and left to guess. It finds the minimal set of rules that can't all hold together, and separately how far each would have to move. And if you want to know what a constraint is costing you, you can ask for its shadow price, or just tell it to loosen that constraint and re-solve, and see what changes.

None of this is clever. It's the stuff a careful modeler does anyway. The only idea here is to make an agent do it too, by making the shortcuts unavailable rather than just discouraged.

## Quickstart

```python
from finalops import CapacityLimit, DemandCoverage, Ledger, run

ledger = Ledger()

ledger.variable("widgets", units="units/week", source="brief.md:2")
ledger.variable("gadgets", units="units/week", source="brief.md:2")

ledger.data("widget_cost", 3, units="$/unit", source="brief.md:1")
ledger.data("gadget_cost", 5, units="$/unit", source="brief.md:1")

ledger.minimize("cost", {"widgets": "widget_cost", "gadgets": "gadget_cost"}, source="brief.md:1")

ledger.constrain(DemandCoverage(id="demand", required=100, covered_by=["widgets", "gadgets"], source="brief.md:3"))
ledger.constrain(CapacityLimit(id="capacity", limit=240, uses={"widgets": 1, "gadgets": 2}, source="brief.md:5"))

outcome = run(ledger, time_limit=300, max_gap=0.05, out="report.json")
print(outcome.passed, outcome.problems)
```

That's the whole model. There's no `pulp` import and no model object: the ledger is the model. `run()` builds it, solves it, checks feasibility, checks ledger coverage, tests the answer against every rule, checks the quality gap, and hands back a single `RunResult(passed, report, problems, model)` — instead of making you chain solve → build_report → check as separate steps you could stop short of. `outcome.problems` is just a list of plain strings ("infeasible: requirement 'demand' violated by 10", "1 ledger requirement(s) never linked...") you can read directly, or have an agent read directly. The PuLP model it built is `outcome.model`, if you want it.

If you'd rather gate from the shell — CI, or an agent that isn't Python — instead of from inside the script:

```bash
finalops check report.json --max-gap 0.05
```

`check` reads the `report.json` that `run()` already wrote and exits non-zero with the same diagnostics if anything's wrong.

## The four requirement categories

Every ledger requirement has a `kind`, in the order a brief actually gets worked through, and each has one call:

1. **`decision_variable`**: what can be chosen. `ledger.variable("hours", units="hours/week", upper=40, source=...)`. Units get stored explicitly, because a dropped or mismatched unit is exactly the kind of thing that slips past everyone until it doesn't. The id is the variable's name, so it has to be a plain identifier. `category="Integer"` or `"Binary"` makes it discrete.
2. **`objective`**: what "good" means. `ledger.minimize("cost", {"widgets": 3, "gadgets": 5}, source=...)`, or `ledger.maximize(...)`. A coefficient is a number, or the id of a data entry.
3. **`constraint`**: what's not allowed, logical (you can't work a negative number of hours) or specific to the brief. `ledger.constrain(CapacityLimit(...))`, described in the next section.
4. **`data`**: the hard numbers everything above is built from. `ledger.data("widget_cost", 3, units="$/unit", source=...)`. Anywhere a rule or the objective takes a number, it can take that id instead, so the `3` in the model carries its units and its source with it. Data that nothing ever uses shows up as `UNLINKED`.

`finalops ledger list` shows the units and what each one became. This is the actual output for the Quickstart:

```
[linked  ] widgets (decision_variable): widgets  <- brief.md:2 [units: units/week]
           -> widgets: Continuous variable, bounds=[0, +inf], units=units/week
[linked  ] widget_cost (data): widget_cost  <- brief.md:1 [units: $/unit]
           -> data: 3 $/unit (used by cost)
[linked  ] cost (objective): cost  <- brief.md:1
           -> objective: 5*gadgets + 3*widgets
[linked  ] capacity (constraint): capacity  <- brief.md:5
           -> capacity: 2*gadgets + widgets <= 240.0
```

See `examples/production_plan.py` for the full walkthrough.

You can also write the checklist first: `ledger.add(id="safety_stock", description="keep 20 units back", source="brief.md:footnote")` records a requirement from the brief with no math yet. Defining it later (`ledger.constrain(...)` with the same id) attaches the math to it. One you never define stays `UNLINKED`, and `run()` says so.

## Rules are objects

Every rule is a `Constraint` subclass. You fill in named parameters and the class supplies the algebra, so there's no `x + 2 * y <= 240` to get subtly wrong. Two ship today:

| Class | Says | Parameters |
|---|---|---|
| `CapacityLimit` | a resource can't be used past a limit | `limit`, `uses` (variable → amount used per unit) |
| `DemandCoverage` | demand has to be met | `required`, `covered_by` (a list, or variable → contribution per unit) |

Each takes the fields every requirement has (`id`, `source`, `description`, `units`), and unknown fields are rejected, so `limt=240` is an error rather than a rule that quietly has no limit. Naming a variable that doesn't exist fails with the ones that do:

```
UnknownVariableError: no variable named 'widgts'. Declared variables: gadgets, widgets
```

For a rule none of the classes express, there's an escape hatch. `CustomConstraint` takes a function that receives the model and returns a PuLP constraint, and an optional `check_fn`:

```python
from finalops import CustomConstraint

ledger.constrain(CustomConstraint(
    id="mix",
    source="brief.md:9",
    description="at least as many gadgets as widgets",
    build=lambda m: m.var("gadgets") >= m.var("widgets"),
))
```

**What the second check is worth.** After the solve, every rule's `check` re-tests the answer in the rule's own terms, separately from the constraint that went to the solver. If a rule's algebra doesn't say what the rule says, the solver will happily satisfy the wrong thing and the check will catch it: `tests/test_specs.py` has a `CapacityLimit` whose `compile` allows 10 too many, and `run()` reports `rule 'cap' violated: uses 110 units against a limit of 100`.

But be clear about what that does and doesn't cover. For a plain linear rule like these, `check` restates the same formula as `compile`, so it guards against encoding bugs, not against misreading the brief: whoever picks the class and fills in the numbers can still get them wrong. It earns its keep on rules whose everyday meaning differs from their algebra (an "if this then that" rule written with a big-M constant, say), and those classes aren't written yet.

A ledger saved with `ledger.to_json("ledger.json")` carries the specs, so the whole model round-trips through a file. A `CustomConstraint` holds a function and can't be saved.

## Dropping down to PuLP

The ledger API sits on top of a `Model` wrapper, which you can use directly when you'd rather write PuLP yourself. Every variable, constraint and the objective still has to cite a ledger id, and a rule you never wired up still shows as `UNLINKED`:

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

outcome = run(model)
```

`model.add_variable(var, requirement_id=..., units=...)` links a variable, `model.cite_data(requirement_id, note="3.0 $/unit, from data/costs.csv")` records a number by citation, and `model.add(rule)` adds a rule object to a model you built by hand. The two styles mix.

## Explaining an infeasibility

"Infeasible" is where most modeling sessions stall, and by default the solver tells you nothing more. CBC and HiGHS don't ship an IIS (irreducible infeasible subset) finder the way some commercial solvers do. So `explain_infeasibility` returns two answers, both tied back to ledger requirements:

- **`conflict`**: a minimal set of rules that can't all hold together. Take any one out and the rest can be satisfied. This is the "which rules are fighting" answer, and it includes variable bounds, not just constraints.
- **`violations`**: relax every constraint with a penalized slack and minimize total violation. This is the "how far do I have to move" answer (`relax capacity by 12`). It is one cheap way out, not the whole conflict, so it often names fewer rules than the conflict does.

```python
import pulp
from finalops import Ledger, Model, explain_infeasibility

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
model.add_constraint(bread + 2 * cakes <= 100, requirement_id="oven_hours")     # bread 1h, cake 2h
model.add_constraint(1.5 * bread + cakes <= 200, requirement_id="labor_hours")
model.solve()

diagnosis = explain_infeasibility(model)
print(diagnosis.conflict.requirement_ids, diagnosis.conflict.minimal)
# ['contract_bread', 'contract_cakes', 'oven_hours'] True
for v in diagnosis.violations:
    print(v.requirement_id, v.magnitude)
# contract_cakes 10.0
```

The two contracts need 60 + 2×30 = 120 oven hours and the oven has 100. The labor limit is a bystander, so it isn't in the conflict. The relaxation names only `contract_cakes` (30 cakes → 20 fixes it), which is a valid fix but hides that the other two rules are equally part of the problem.

The conflict is found with a deletion filter: drop items in chunks, keep each drop if what's left is still infeasible, and finish with a one-at-a-time pass, so what survives is minimal. That's a few solves for a small model and roughly log-many per conflict member for a large one, capped by `max_conflict_solves` (default 200); if the cap hits, you still get a real conflict, flagged `minimal: False`. Integrality is left in place while searching, so an integer model that's infeasible only because of integrality is found too. `find_conflict(model)` gives you just the conflict.

`run()` does all of this automatically whenever the solver proves infeasibility, so `outcome.problems` leads with a line like `"infeasible: these cannot all hold together: 'contract_bread' (at least 60 loaves/day), 'contract_cakes' (...), 'oven_hours' (...). Loosen or drop any one of them and the rest can be satisfied"`, and `outcome.report["conflict"]` carries the same thing as structured data (`members`, each with a `requirement_id`, `expression` and `description`, plus `minimal`).

## Sensitivity & what-if analysis

Continuing the model from [Quickstart](#quickstart) — it's feasible, so there's something to analyze. `binding_report` tells you, per requirement, whether its constraint is binding, how much slack it has, and its shadow price. Exact for continuous LPs; for MIPs it's computed against the LP relaxation, and tagged as such, so an approximate dual never gets presented as an exact one:

```python
from finalops import binding_report

report = binding_report(outcome.model)
for r in report.requirements:
    print(r.requirement_id, "binding=", r.binding, "shadow_price=", r.shadow_price)
```

`requirement_impact` answers "what if" without you having to hand-edit the model: drop a requirement's constraint entirely, or shift its bound, re-solve, and see what actually changed. It's a real re-solve, not analytic ranging, so it's correct for MIPs too:

```python
from finalops import requirement_impact

impact = requirement_impact(outcome.model, "capacity", rhs_delta=20)
print(impact.objective_delta, impact.binding_flips)
```

## The debugger

A number and a status word don't tell you why a model behaves the way it does. `build_debug_bundle` solves the model and writes everything needed to explain the result into one JSON file: the ledger, every variable and constraint with its slack and shadow price, the solver's bound, the infeasibility diagnosis if there is one, and, for each constraint, what happens if you drop it and re-solve.

```python
from finalops import build_debug_bundle

build_debug_bundle(ledger, out="bundle.json")   # or pass a Model
```

The viewer is the Next.js app at the root of this repo. It draws the model as a graph (variables on the left, the objective and constraints on the right, coefficients on the edges) and tells you what's binding, or, if the model is infeasible, which rules conflict, drawn in red on the graph. Click any requirement to see the constraint it became. Load your own `bundle.json` with the button at the top, or pick one of the samples:

```bash
pnpm install && pnpm dev     # from the repo root, then open http://localhost:3000
python examples/generate_debug_samples.py   # regenerates public/samples/
```

It's a static viewer: it can't re-solve for you live, which is why the "if dropped" answers are worked out ahead of time, one extra solve per constraint. An unbounded model gets its own diagnosis (`unbounded`, not `infeasible`), and a rule that's in the ledger but was never wired into the model shows up as `unlinked`.

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

`finalops ledger add` records a requirement from the brief with no math yet, the checklist-first path. A ledger saved from Python with `ledger.to_json()` also carries the rule specs and the links, so `list` and `graph` show what each requirement became.

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

## License

[MIT](../LICENSE)
