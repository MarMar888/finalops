# Wishlist

What an OR tool needs in order to be a good fit for an agent, beyond the general AI-native basics. OR CLIs are a natural place for this because the domain already speaks in structured objects: constraints, variables, bounds, duals. Nothing has to be retrofitted onto output that was designed for a human to scroll through.

Each item below says where finalops stands today.

| Item | Status |
| --- | --- |
| Infeasibility diagnosis (IIS / conflict set) | Built |
| Sensitivity output as typed objects | Partly built |
| Explain the model, separate from solving it | Partly built |
| Capability introspection | Not started |
| Terse by default | Not started |
| Error taxonomy | Partly built |
| Reproducibility metadata on every solve | Not started |

## Infeasibility diagnosis

The single highest-leverage feature. "Infeasible" is the most common dead end in OR work, and by default it tells you nothing. Every serious CLI here should compute an IIS (irreducible infeasible subset) or a conflict set and return it as structured data: which constraints, which bounds, the minimal set that can't all hold. An agent that hits infeasible and gets back `{"status": "infeasible", "conflicting_constraints": [...]}` can actually propose a fix. An agent that gets back "Model infeasible" and a log dump just guesses or gives up.

**Status: built.** `find_conflict` / `explain_infeasibility` return a minimal conflict set (constraints and variable bounds, each tied to its ledger requirement), plus the cheapest relaxation and how far each rule has to move. It's in `outcome.report["conflict"]` and the debug bundle. Gaps: it finds one IIS, not every overlapping one; integrality is held fixed while searching; and it's a Python API and bundle field, not yet a CLI command.

## Sensitivity output as a first-class object

Shadow prices, reduced costs, binding vs. slack constraints, ranging: these are gold for an agent trying to explain why a solution looks the way it does, or to answer "what if I relax this constraint." Most tools bury them in a text report meant for a human analyst. Return them as a typed object by default (or behind a cheap flag) instead of something you have to regex out of solver output.

**Status: partly built.** `binding_report` returns slack, binding and shadow price per requirement (exact for LPs, LP-relaxation and tagged as such for MIPs), and `requirement_impact` answers "what if I drop this" by re-solving. Missing: reduced costs, ranging (how far a coefficient or right-hand side can move before the basis changes), and a CLI command for any of it.

## Separate "explain the model" from "solve the model"

A validate / dry-run mode that checks dimensions, reports unused variables, flags obviously redundant or contradictory constraints, and returns that as structured warnings before you burn solver time. Agents build models programmatically and make dumb structural mistakes constantly (off-by-one indexing, wrong sense on a constraint). Catching that before the solve is far more useful than after.

**Status: partly built.** Building from a ledger already fails fast on an unknown variable or data id (and lists the real ones), and requirements or data nothing uses are reported as `unlinked`. Missing: a dry-run mode that stops before the solver, unit and dimension checks, unused variables, redundant or contradictory constraints, and a wrong-sense heuristic.

## Capability introspection

Which solvers are actually available (HiGHS, CBC, GLPK, commercial if licensed), what problem classes each supports (LP/MIP/QP/NLP), time limits, gap tolerances. An agent needs to query this before deciding how to call the tool, the same way it would check which tools are in scope. Don't make it guess or fail-and-retry to find out.

**Status: not started.** CBC is the only solver finalops drives.

## Terse by default, everything else behind a flag

Default output: status, objective value, solve time, gap. The full solution vector, duals and solver log are opt-in. A model with 5,000 variables shouldn't dump 5,000 lines on an agent that just needs to know whether it's optimal.

**Status: not started.** `run()` returns a fixed-shape report and the debug bundle includes everything. There's no verbosity control and no `finalops run` command yet.

## Error taxonomy that branches cleanly

Malformed input vs. infeasible vs. unbounded vs. timed out vs. solver crashed. These need genuinely different agent responses (fix the model, relax constraints, increase the time limit, try another solver), so collapsing them into one generic failure kills the ability to self-correct.

**Status: partly built.** Infeasible and unbounded are reported separately, each with its own diagnosis, and malformed specs raise typed errors (`UnknownVariableError`, `UnknownDataError`, validation errors). Time-limited solves are told apart from proven-optimal ones via CBC's own termination line, because PuLP labels a partial search "Optimal". Missing: a single taxonomy an agent can branch on (with matching CLI exit codes), and handling for a solver crash.

## Reproducibility metadata on every solve

Solver name and version, seed, tolerances, wall time. MIP solvers especially can return different (equally optimal) solutions from run to run, and an agent debugging "why did this change" needs that context returned with the result, not buried in a log it has to opt into.

**Status: not started.** The report records the solver's termination line and bound, but not the solver version, seed, tolerances or wall time.
