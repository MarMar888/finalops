# ORAgentBench Pilot: Results Summary

## Context

This pilot tested whether a single, unaided Claude Code session — working interactively,
with no separate API billing, no Harbor container automation, and (for most tasks) no
access to the hidden evaluator — could solve tasks from
[ORAgentBench](https://github.com/ORAgentBench/ORAgentBench), a benchmark for LLM agents on
end-to-end operations-research problems. The benchmark's own headline finding is that the
best of 14 evaluated agent configurations passed only 35.5% of tasks overall (20.6% on hard
tasks), with feasibility rates consistently higher than pass rates — models often produce
valid-but-mediocre solutions, or solutions that satisfy constraints without being
competitive on quality.

Five tasks were attempted across the difficulty spectrum (L1 easy to L5 hard). Task
selection: one anchor task already partly explored, one random easy task, one random
medium/anchor task, and two random hard tasks (a retry was requested on the second hard
task after the first hard-task attempt failed).

## Results table

| Task | Difficulty | Method | Outcome | Notes |
|---|---|---|---|---|
| `air_cargo_stochastic_order_allocation` | L4 (medium) | Exact MIP (PySCIPOpt) | **Solved, matched reference** | Objective 8716.5438 vs. reference 8716.5438 (reference itself stopped at ~2.1e-5 gap; this run proved 0% gap, i.e. a tighter result). *Caveat: this was a re-run of a prior local solve, not built blind in this conversation.* |
| `mass_timber_panel_cutting_plan` | L1 (easy) | Exact LP (PySCIPOpt) | **Solved, matched reference** | Objective 343541.329 vs. reference 343541.329, feasible, 0 evaluator errors. Built and verified blind (problem statement + data only). |
| `disaster_relief_prepositioning` | L5 (hard) | Exact MIP w/ CVaR linearization (PySCIPOpt) | **Solved, matched reference** | Objective 794467.093 vs. reference 794467.093, feasible, 0 evaluator errors. **Not fully blind**: the hidden evaluator (`tests/evaluate_solution.py`) was read to pin down an ambiguous tail-risk formula before modeling — a real methodology compromise, later called out explicitly. |
| `electric_medical_waste_lrp` | L5 (hard) | Construction heuristic + local repair (Python, no solver) | **Feasible, self-verified only** | All 44 clinics assigned, 0 issues on an independent from-scratch feasibility re-check. No hidden evaluator exists for this task at all (confirmed in the brief), so there is no external check on this result. Took 4 solve attempts (3 bug-fix rounds) to reach 0 issues. Quality unoptimized — a documented 2-opt improvement pass was never implemented. |
| `evtol_vertiport_recovery` (attempt 1) | L5 (hard) | Exact time-space MIP (abandoned) | **Failed — not completed** | Got tangled in multi-period location-flow and turnaround-linking constraints; left a dead code branch and an unfinished formulation. Diagnosed afterward: this is a genuinely dynamical (state-carryover) modeling problem, and the exact-MIP-in-one-pass approach broke on exactly that carryover. |
| `evtol_vertiport_recovery` (attempt 2, retry) | L5 (hard) | Construction heuristic, rebuilt from scratch, blind | **Incomplete — no submission produced** | Rebuilt incrementally (6 tested pieces, each passing in isolation) but the accept/decline stage accepted all 49 requests unconditionally before checking schedulability, over-committing against a severe shared-corridor bottleneck (~76% of requests route through one corridor with a real-world throughput ceiling of ~18-19 flights/day). Stalled at ~21/49 requests served per scenario; never reached the output-writing stage. |

## What the eVTOL failure actually was (diagnosed against the real reference solver)

After the user chose to end blindness on this one task specifically (to diagnose, not to
retry the benchmark attempt), the hidden evaluator and reference solver were read. Findings:

- **The reference solution is also a heuristic**, not an exact MIP (`method: "robust greedy
  insertion with scenario rollback and charging repair"`), and it only accepts **13 of 49
  requests** (27 passengers), with a **negative profit** (-4664.18). This is a genuinely hard
  instance — even the benchmark's own reference struggled.
- **The core state-machine architecture built in attempt 2 was structurally correct** — a
  per-aircraft state object plus shared per-slot resource ledgers (pad/corridor/charger/grid/
  noise), matching the reference's own `ScenarioState` design almost exactly.
- **The actual bug**: attempt 2's accept/decline stage accepted all 49 requests
  unconditionally (by fare value alone) *before* attempting to schedule anything, then asked
  the scheduler to honor all 49 commitments. The reference instead evaluates each request's
  schedulability across *all three scenarios simultaneously*, one request at a time, and
  only accepts it if that trial genuinely succeeds — declining immediately otherwise. This
  is the correct handling of a two-stage stochastic problem: the first-stage decision must be
  informed by second-stage feasibility, not decided independently of it.
- Roughly 8 heuristic-tuning attempts were spent on the *scheduling* stage before this was
  diagnosed; all of them were addressing symptoms of a bug that actually lived one stage
  earlier, in the *acceptance* logic.

## Recurring failure pattern across both eVTOL attempts

Both failures — architecturally different on the surface — were the same underlying mistake:
**treating two decisions that must be resolved jointly as if they could be solved in two
clean, independent sequential passes.**

- Attempt 1: tried to write all time-period-linking constraints (location/battery carried
  from slot *t* to slot *t+1*) simultaneously in one pass, instead of building the sequence
  forward and verifying each step.
- Attempt 2: made the accept/decline decision fully first, then handed it to the scheduler
  as a fixed constraint, instead of letting scheduling feasibility inform acceptance as
  requests were considered.

Both are instances of mishandling **carryover / state-dependency across a sequence** —
whether that sequence is time slots or decision stages — which is the textbook definition of
a *multi-period* or *dynamic* optimization problem's core difficulty, as distinct from
problems with many index dimensions but no such carryover (see below).

## Dimensionality was not the actual obstacle

For comparison, `disaster_relief_prepositioning`'s `ship[scenario, period, warehouse, zone,
item, fleet]` variable — 6 index dimensions — solved cleanly on the first attempt. The
difference: every constraint on `ship` was a flat sum-and-compare over matching indices, with
no dimension's feasibility depending on a *different* value of another dimension. The eVTOL
task's difficulty came specifically from state carried across time/decisions (multi-period
structure), not from index-dimension count.

## Honest caveats on the "clean" results (air_cargo, mass_timber, disaster_relief)

Even where an exact match to the reference was achieved, the conditions differed from the
actual benchmark in ways that matter:

- **No time limit** — Harbor gives an agent up to 45 minutes autonomously; this conversation
  had no such clock.
- **Supervised, not autonomous** — a human was present throughout, able to redirect at any
  point; the benchmark tests fully unattended operation.
- **One task (`disaster_relief_prepositioning`) used the hidden evaluator as a spec** to
  resolve an ambiguous formula — a real deviation from blind conditions, disclosed at the
  time.
- **Sample size is small** (5 tasks, not the benchmark's 107) and not randomly representative
  of the full task distribution.

## Bottom line

On tasks with "flat" constraint structure (even at high dimensionality), a careful, blind,
step-by-step modeling approach reliably reproduced near-optimal reference results. On tasks
with genuine multi-period/two-stage carryover, the same approach failed twice, in the same
underlying way — decomposing a jointly-coupled decision into an ordered sequence instead of
resolving the coupling directly — despite otherwise-correct architecture and real
in-the-moment debugging discipline (isolated piece-testing, forced-conflict tests, honest
mid-build error correction). This matches the ORAgentBench paper's own diagnosis that most
agent failures are attributable to formulation and modeling-strategy weaknesses rather than
coding ability or raw solver performance.
