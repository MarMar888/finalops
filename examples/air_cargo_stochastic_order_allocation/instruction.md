You are solving an operations-research benchmark task inside a sandbox.

Work only inside `/app`. Do not use the internet, hidden evaluator files, reference models, package registries, or remote data.

Required workflow:
1. Read `/app/PROBLEM_STATEMENT.md`, and every file under `/app/data/`.
2. Write a complete mathematical model to `/app/submissions/model.md` before finalizing code.
3. Implement the solver in `/app/submissions/solve.py` using PySCIPOpt.
4. Use SCIP relative gap `0.0005`. If `ORCLAW_SOLVE_TIME_LIMIT_SECONDS` is set, use a time limit no larger than that value. Preserve solution values with precision up to `1e-8` after the decimal point.
5. Make `/app/submissions/solve.py` solve from scratch when run as `python /app/submissions/solve.py`.
6. Write the required solution file under `/app/submissions/` using the task schema.
7. Write `/app/submissions/solve_log.md` with commands, solver status, objective or score if available, and validation checks.

Note:
You may improve the modeling and solving strategy based on preliminary results, but each individual solve attempt is limited to 5 minutes. The whole workflow is also time-limited, so do not perform unlimited full solve-and-iterate cycles.

Before running expensive solves, reason about the problem structure and choose an efficient approach. You may:
1. Use stronger mathematical formulations and more sophisticated modeling strategies tailored to the structure, special properties, and scale of the given problem instance.
2. Solve directly with SCIP when the model is tractable.
3. Design effective heuristic, local-search, repair, or rounding methods when exact optimization is too slow.
4. Combine heuristics with SCIP, for example by generating an initial feasible solution, fixing or relaxing selected variables, using warm starts if supported, or solving restricted subproblems.
5. Run short diagnostic solves to estimate difficulty, then refine the model or solution method.

Do not default to a naive formulation. Before coding, explicitly analyze whether the problem is better represented as an assignment model, network flow model, set partitioning model, time-indexed model, interval/order-based scheduling model, routing model, or decomposition-based model and so on. Choose the formulation that is likely to give the strongest relaxation and fastest solution for the given instance size. Use preprocessing, dominance filtering, bound tightening, valid inequalities, symmetry breaking, and heuristic warm starts whenever applicable.

Use the limited iteration budget wisely:
- First ensure feasibility and correct output schema.
- Then improve objective quality.
- Prefer targeted refinements over repeated full solves.
- Stop iterating when additional improvements are unlikely within the remaining time.
- Record every meaningful solve attempt and validation result in `/app/submissions/solve_log.md`.

The final submission should prioritize correctness, feasibility, and robust execution from scratch under the time limit.
