---
name: optimization-solver-repair
description: Use when optimization solver code crashes, produces no solution, is rejected by a checker, or returns infeasible/unbounded; guides repair by distinguishing code errors from modeling errors and keeping the written model and code synchronized.
metadata:
  short-description: Repair failing optimization solver code
---

# Optimization Solver Repair

## Use when

- Solver code raises an exception, such as `SyntaxError`, `ImportError`, `KeyError`, bad tuple indexing, missing columns, or invalid solver API use.
- A solve finishes with `INFEASIBLE`, `INF_OR_UNBD`, `UNBOUNDED`, no incumbent, or an evaluator rejection.
- The user asks to fix a submission, reference solver, benchmark solver, or generated optimization code.
- There is a written formulation file such as `model.md`, `MODEL.md`, `formulation.md`, or a task report that must stay consistent with the code.

## Do not use when

- The task is only to design a new model from scratch and no failing implementation exists.
- The user only asks for a high-level explanation of solver output.
- The failure is clearly outside the optimization layer, such as a broken package install or unrelated CI setup, unless it blocks running the model.

## Triage boundary

Classify the failure before editing:

1. **Syntax/import failure**: code cannot start.
2. **Data/schema failure**: files, columns, keys, units, or types do not match the code.
3. **Solver API failure**: variables, tuple keys, expressions, or attributes are used incorrectly.
4. **Model-status failure**: the solver runs but returns infeasible, unbounded, no incumbent, or a bad gap.
5. **Evaluator failure**: the solver returns a solution, but external checks reject feasibility, schema, or objective.

Fix only enough code to expose the real modeling issue. Do not treat a syntax or tuple-indexing fix as proof that the mathematical model is correct.

## Runtime error workflow

1. Re-run the exact failing command and capture the first meaningful traceback.
2. Locate the failing line and identify whether the issue is syntax, data/schema, solver API, or modeling logic.
3. If it is a pure syntax/import/path issue, repair it directly and re-run.
4. If it is a key/index/schema issue, compare code assumptions against the actual data and written model.
5. If code and the written model disagree, update the written model first when the model was wrong, or update the code first when the implementation drifted from the model.
6. Re-run the solver and checker; do not stop at "script exits cleanly" if the output is infeasible or rejected.

## Common code-error causes

- Tuple-key mismatch from solver APIs flattening nested tuples.
- Missing eligibility filters, causing variables to be accessed for nonexistent combinations.
- Data columns renamed, quoted incorrectly, parsed as strings, or using different units.
- Reading relative paths from the wrong working directory.
- Accessing variable `.X` before confirming a solution exists.
- Treating a time-limit status with no incumbent as a valid solution.
- Exporting rounded or incomplete rows that break checker recomputation.

## Infeasible workflow

1. Confirm the status is truly infeasible and not `INF_OR_UNBD`; disable dual reductions or rerun as needed if the solver supports it.
2. Generate an IIS or conflict explanation when available.
3. Do not load the full `.ilp`/IIS file into context when it is large. First extract a compact summary by constraint name, bound name, and rule prefix.
4. Map the dominant IIS prefixes back to business rules, data rows, and equations in the written model.
5. Inspect only representative constraints from the suspicious rule families, then pull more detail only if the cause is still ambiguous.
6. Check for the smallest contradiction: demand exceeds capacity, mandatory commitments exceed demand, eligibility is empty, time windows conflict, inventory starts wrong, fixed lower bounds force impossible activity, or two logical implications conflict.
7. Decide whether the error is in the written model, data, solver code, or evaluator/checker.
8. If the written model is wrong or incomplete, update `model.md` or the equivalent formulation document first.
9. Modify solver code to match the corrected model.
10. Re-run the solve, export, evaluator/checker, and at least one targeted sanity test.

## IIS extraction strategy

Use IIS as a diagnostic lens, not as text to paste wholesale.

1. Ensure constraints are named by rule family and key, for example `demand_balance[item,period]`, `capacity[resource,period]`, `eligibility[item,resource]`, or `time_window[job]`.
2. If names are vague, add names to the main hard constraints and rerun IIS before analysis.
3. Write the IIS to a file if supported, then summarize it with scripts or shell tools:
   - Count IIS constraints by prefix before inspecting individual rows.
   - List the first few names per prefix.
   - Search for the specific entity, period, resource, route, or product that appears repeatedly.
   - Include bounds in the summary; variable lower/upper bounds in IIS often reveal forced decisions.
4. Inspect full constraint expressions only for the smallest suspicious subset, not the entire IIS.
5. If the IIS is still huge, create a reduced instance around the repeated keys and rerun IIS on that small case.

## IIS interpretation boundaries

- IIS shows one conflicting subsystem, not the whole cause. Do not blindly remove every constraint in the IIS.
- A constraint appearing in IIS is not necessarily wrong; it may only be exposing bad data or a missing relaxation elsewhere.
- Start with rule families that create hard equalities, hard lower bounds, fixed assignments, capacity ceilings, and eligibility exclusions.
- Treat variable bounds as constraints. A binary fixed by preprocessing or a lower bound on shipment/production can be the real conflict.
- If data rows appear repeatedly in IIS keys, verify whether the data is invalid or whether the model interpreted the row too strictly.
- If a relaxation variable should exist but does not, add it intentionally with a documented penalty instead of weakening a hard constraint silently.
- If solving a benchmark or public task, do not "fix" infeasibility by changing public data unless the task is to repair or author the instance.

## IIS root-cause patterns

- **Empty eligibility**: a demand, shift, shipment, or job is mandatory but no allowed resource can cover it.
- **Overcommitted capacity**: fixed demand, contracts, or assignments exceed period/resource capacity.
- **Bad conservation**: inventory, flow, or route balance has inconsistent initial, terminal, or transit assumptions.
- **Conflicting time logic**: service, travel, setup, rest, or time windows make a mandatory sequence impossible.
- **Activation mismatch**: activity requires a resource to be open, but another rule forces it closed.
- **Too-tight logical equivalence**: the code modeled `A <-> B` when the business only required `A -> B`.
- **Missing slack by design**: the written model says shortage/postponement is allowed but the code forgot the slack variable.
- **Unit mismatch**: capacity and demand are in different units or periods.

## IIS-driven repair order

1. Name or summarize the conflicting rule families.
2. Identify the smallest data keys involved, such as one item-period, one job-resource pair, or one route segment.
3. Re-read the written model for those rules and decide whether the math matches the intended business rule.
4. Update `model.md` first if the formulation was incomplete, too strict, or semantically wrong.
5. Patch solver code second, keeping variable names and constraint groups aligned with the revised model.
6. Rerun IIS only if infeasibility remains; otherwise proceed to normal solve and evaluator validation.

## Model-document synchronization

- Treat the written model as the source of design intent when it is current and correct.
- If debugging proves the written model was wrong, revise it before patching code.
- Keep variable definitions, objective terms, and constraint groups aligned between document and implementation.
- Record any changed assumption, such as allowing shortage, changing equality to inequality, adding slack, changing a time-window convention, or tightening activation logic.
- If no `model.md` exists, update the nearest modeling note, report, or code comments that define the formulation.

## Evaluator-rejection workflow

1. Validate output schema before interpreting optimization quality.
2. Recompute feasibility from the exported solution, not only from in-memory variables.
3. Recompute each objective component and compare with the evaluator.
4. If the evaluator checks a stateful rule, replay the state chain in order, such as inventory periods, route events, machine schedules, or staff shifts.
5. If the evaluator is correct, repair the written model and solver code. If the evaluator is wrong and in scope, repair evaluator and reference solver together.

## Verification checklist

- The failing command now runs.
- Solver status and incumbent availability are handled explicitly.
- The written formulation and solver code describe the same model.
- Feasibility is checked by solver status and by exported-solution validation.
- Objective value is recomputed from the export.
- Any infeasibility repair has a trace from IIS/conflict to business rule to model/code change.
- The final notes mention whether the fix was syntax, data/schema, solver API, modeling logic, or evaluator logic.
