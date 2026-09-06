# Sensitivity & visibility layer — plan

## The problem this addresses

Talked through with Patrick on 2026-09-06. Summarized:

LLM agents (and humans) building OR models with PuLP struggle across the whole
build loop — identify problem, collect data, formulate constraints, solve,
test, discover a missing/wrong constraint, adjust, re-test. Two compounding
failures:

1. **No visibility into consequence.** When a constraint is added, removed, or
   changed, there's no easy way to see *what actually shifted* in the model's
   behavior (objective, which constraints are binding, which are slack, which
   variables moved). Without that, you can't tell a real constraint from an
   assumed one, and iteration becomes guesswork.
2. **No triage when something breaks.** When a model is infeasible or the
   result looks wrong, there's no fast way to tell whether the problem is
   upstream (bad/misinterpreted data), in the formulation (wrong or missing
   constraints — partially addressed already by the ledger), or in solver
   usage (wrong solver/assumptions/time limit/gap tolerance for the problem
   at hand). Effort gets spent re-guessing instead of going to the right
   layer.

`finalops` already has a ledger (`Ledger`, `Model`) that forces every
constraint to cite a requirement id, and a validate/report layer
(`check_feasibility`, `quality_gap`, `build_report`) that gates on "did it
actually work," not just "did it run." This plan adds the missing piece:
**what changed, and why**, expressed in the same requirement-id vocabulary
the ledger already uses.

## Scope of v1

Build the backend piece first: a Python module that, given a solved `Model`,
can answer "for each constraint (== each ledger requirement), was it binding,
how much room did it have, and what would relaxing/tightening it be worth?" —
plus a way to diff two solves against each other when a constraint changes.

The Next.js app at the repo root is the intended frontend for visualizing
this later (rendering constraint impact, maybe a sensitivity/Pareto view).
v1 does **not** build that UI — it builds the backend contract (structured,
JSON-serializable output) that a frontend would consume, and ships a
minimal CLI/table view so the data is usable before any UI exists.

Out of scope for v1: data-layer diagnosis (tracing a bad RHS back to a
source CSV), automatic IIS (infeasible subset) detection, multi-objective
Pareto frontiers, solver auto-selection. These are natural v2+ extensions
once the core "what changed and what's binding" loop is solid — see
Later below.

## What v1 actually computes

Three things, all keyed by `requirement_id` so they line up with the ledger:

### 1. Binding report (per solve)

For every constraint in the model, after a solve:
- `slack` — already computed in `validate.py`, reused here
- `binding: bool` — slack ~0 (within tolerance)
- `shadow_price` — the constraint's dual value (`pulp.LpConstraint.pi`),
  when available. Only rigorous for LP; for MIP, PuLP/CBC will not expose a
  meaningful dual, so this field is `None` and the report says why
  (see "MIP caveat" below).

This answers: *of everything I told the model to respect, what's actually
constraining the answer right now, and what's slack (i.e. currently doesn't
matter, whether or not it's "true")?*

### 2. Requirement impact (what-if, one constraint at a time)

Given a model and a requirement id, temporarily relax or tighten that one
constraint's RHS by a delta (or drop it entirely), re-solve, and report the
objective delta, feasibility change, and which other constraints' binding
status flipped. This is a brute-force re-solve (works for LP and MIP,
correct for any model type) rather than analytic ranging — deliberately
simple for v1, since re-solve cost is acceptable for the model sizes this
targets initially.

This answers: *is this constraint actually costing me anything, or is it
slack and safe to ignore/simplify?* — directly the "how does adding,
removing, or changing a constraint change optimality" question from the
brainstorm.

### 3. Solve diff (compare two solves)

Given two `SolveResult`/report snapshots (e.g. before and after editing the
model), compute: objective delta, which requirements flipped
binding↔slack, which variables changed value and by how much, any
feasibility change. This is the general case of (2) — useful when more than
one thing changed between two versions of the model, not just one constraint.

### MIP caveat (important, must be visible in the output, not buried)

Shadow prices are only mathematically meaningful for continuous LPs. For a
MIP, `finalops` should not silently print a misleading number. v1 behavior:
if any variable is integer/binary, `shadow_price` is computed against the
**LP relaxation** (reusing `relaxation_bound()`, already in `validate.py`)
and every output is labeled `"basis": "lp_relaxation"` vs `"basis": "exact"`
so nobody mistakes an approximation for an exact dual. The re-solve-based
"requirement impact" (item 2) has no such caveat — it's exact for any model
type, which is the main reason to build it even though duals are cheaper.

## Shape of the output

Everything returns as plain dataclasses (`asdict`-able, matching the
existing `report.py` pattern) so it composes with the current JSON report
and is trivial to hand to a future frontend or to an LLM agent as
structured text. Sketch:

```python
@dataclass
class RequirementSensitivity:
    requirement_id: str
    binding: bool
    slack: float
    shadow_price: float | None
    basis: str  # "exact" | "lp_relaxation" | "unavailable"

@dataclass
class SensitivityReport:
    model: str
    basis: str
    requirements: list[RequirementSensitivity]

@dataclass
class ImpactResult:
    requirement_id: str
    change: str  # e.g. "relaxed by 10%", "dropped"
    objective_before: float | None
    objective_after: float | None
    objective_delta: float | None
    feasible_after: bool
    binding_flips: list[str]  # requirement ids whose binding status changed

@dataclass
class SolveDiff:
    objective_delta: float | None
    binding_flips: list[str]
    variable_deltas: dict[str, float]
    feasibility_changed: bool
```

Proposed module: `finalops/src/finalops/sensitivity.py`, following the same
"plain functions over dataclasses, no hidden state" style as `validate.py`.

## Initial steps (in order)

1. **`sensitivity.py`: binding report.** Extend `check_feasibility`'s slack
   computation to also pull `constraint.pi` (dual) where available, tag with
   `basis`. Smallest possible slice — no re-solving, just reading more off
   an already-solved problem. Unit tests mirror `test_validate.py`.
2. **`sensitivity.py`: requirement impact (what-if).** Needs a way to clone
   a `Model` (constraint + RHS + ledger intact) and mutate one constraint's
   RHS or drop it, then re-solve and diff against the original. Reuses the
   `copy.deepcopy` approach already in `validate.relaxation_bound`.
3. **`sensitivity.py`: solve diff.** Given two `SolveResult`s (or two
   reports), compute the diff dataclass above. Pure function, no solving
   involved — easiest of the three once (1) exists to define what
   "binding" means.
4. **Wire into `report.py`/`run()`** (optional, once 1–3 are stable): add
   an opt-in `include_sensitivity=True` flag to `run()` so the existing
   one-call flow can return a `SensitivityReport` alongside feasibility and
   quality gap, without changing existing callers' behavior.
5. **CLI surface**: `finalops sensitivity report.json` prints a table
   (requirement id, binding, slack, shadow price) so the data is usable
   from a terminal before any frontend exists — same spirit as the existing
   `finalops check`.
6. **Frontend sketch** (once 1–3 have real output to point at): a page in
   the Next.js app that reads a `SensitivityReport`/`ImpactResult` JSON and
   renders it — start with a simple table/bar chart of binding vs. slack
   requirements and shadow prices, before attempting anything like a
   Pareto/tradeoff view.

## Later (v2+, not now)

- Data-layer tracing: connect a suspicious RHS or coefficient back to the
  source data (file/row) that produced it, extending `Requirement.source`.
- IIS (irreducible infeasible set) detection for infeasible models, so
  "which constraints conflict" is answered automatically instead of via
  manual what-if.
- True multi-objective Pareto frontier support (sweep a second objective as
  a constraint, trace the tradeoff curve) — distinct from single-objective
  RHS ranging, larger effort.
- Solver selection/diagnosis: detect "wrong solver for this problem shape"
  or "time limit hit, reporting best-known as if optimal" as a distinct
  failure category in `diagnose()`.
- Additional solver backends (OR-Tools, HiGHS) — mentioned as a future
  direction in the existing README's Status section; would let sensitivity
  duals be "exact" more often (HiGHS reports duals for LP relaxations of
  MIPs more usefully than CBC in some cases).

## Open questions to revisit with Marley

- Re-solve cost for "requirement impact": fine for small/medium models: for
  large ones, may need a cheaper analytic approximation later. Not blocking
  v1.
- Where the line is between "backend computes this" and "frontend computes
  this from raw data" — e.g. should `binding_flips` be computed in Python
  or should the frontend receive two full reports and diff them
  client-side? Leaning backend (keeps the frontend dumb and the diff logic
  testable), but worth confirming once there's a real UI sketch.
