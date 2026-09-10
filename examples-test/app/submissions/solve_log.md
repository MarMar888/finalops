# Solve Log

Command: `python solve.py`

- SCIP status: `optimal`
- Time limit used: 300.0 s (ORCLAW_SOLVE_TIME_LIMIT_SECONDS honored, capped at 300s)
- Relative gap setting: 0.0005
- Elapsed wall time: 0.08 s
- Objective (profit): 8716.54382400
- Dual bound: 8716.54382400
- Reported gap: 0.0
- Accepted orders: 34

Solution written to `C:\Users\patri\Programming\finalops\examples-test\app\submissions\solution.csv` with schema `row_type,order_id,aircraft_id,value`.

## Independent validation (tests/evaluate_solution.py)

Command:
```
python tests/evaluate_solution.py --solution app/submissions/solution.csv --env-dir app
```

Result:
- `feasible: true`, `error_count: 0` — no route/eligibility/capacity/ramp-team/service-floor violations across any of the 12 scenarios.
- `profit` / `objective`: `8716.543824000004` — matches SCIP's reported objective to 8+ decimal places (`8716.54382400`).
- `accepted_order_count`: 34.
- `expected_profit_before_tail`: 9030.043824000004; `expected_carbon_penalty`: 32.201676; `priority_tail_penalty`: 313.5 (worst_priority_shortfall = 11.0, SC12).
- This matches `tests/reference_metrics.json`'s `reference_objective` (8716.543824000004) and `accepted_order_count` (34) exactly, and SCIP's own dual bound (8716.54382400) equals the primal bound, so the solve is certified globally optimal (0% gap), not merely gap-limited like the reference run (which stopped at `gaplimit` with mip_gap ≈ 2.1e-5).

## Modeling/solving notes

- Formulation: deterministic-equivalent MIP (assignment + per-scenario multi-dimensional knapsack side constraints), documented in `model.md`. All uncertainty is exogenous (`show_{s,o}`, capacity factors), so no per-scenario recourse variables are needed beyond bookkeeping (carbon overage, priority shortfall) — a single first-stage assignment `x_{o,k}` is optimized against all 12 scenarios simultaneously.
- Size (42 orders x up to 7 eligible aircraft, 12 scenarios) let SCIP presolve to 144 variables / 186 constraints and solve to proven optimality at the root node in 0.08s — well under the 300s cap, so no heuristics, decomposition, or warm start were required.
- Only one solve attempt was needed; no iteration was required since the first formulation reproduced the reference objective/accepted-count exactly and passed the evaluator with zero errors.
