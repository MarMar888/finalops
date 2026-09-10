---
name: or-pyscipopt
description: Use when building, running, validating, or debugging Python optimization models that use PySCIPOpt and SCIP.
metadata:
  short-description: Build and run PySCIPOpt models
---

# OR PySCIPOpt

## Use when

- The task asks for a Python optimization model using SCIP or `pyscipopt`.
- Existing solver code imports `pyscipopt`, sets SCIP parameters, writes `.lp`/`.mps`, or calls a SCIP-based checker.
- The user asks to run, debug, speed up, validate, or explain a SCIP-based solve.

## Do not use when

- The task only needs a mathematical formulation and no solver-specific code.
- The project clearly uses a different solver stack, such as Pyomo with CBC/HiGHS, OR-Tools CP-SAT, PuLP, CPLEX, or cvxpy, unless the user asks to port it to PySCIPOpt.
- The model is nonlinear or stochastic in a way that SCIP cannot handle directly; first decide whether it can be linearized or approximated.

## Environment rule

Use the Python environment specified by the user or the project. In this ORClaw workspace, the default solver environment is the `or` conda environment with PySCIPOpt available:

```bash
conda run -n or python <script.py>
```

If `pyscipopt` is missing, report the missing dependency, identify the command that failed, and try the project-specified environment before changing solver stacks.

## Workflow

1. Read the task brief and input files before coding.
2. Write the full mathematical model first: sets, parameters, decision variables, objective, and constraints.
3. Implement the model with explicit tuple keys and named constraints.
4. Solve with the selected Python command.
5. Export the solution using the exact schema required by the task.
6. Validate with the task checker or an independent recomputation of feasibility and objective.
7. If the solution is not accepted, diagnose whether the issue is formulation, data parsing, export formatting, tolerance, or evaluator mismatch before changing the objective or constraints.

## PySCIPOpt patterns

- Use `from pyscipopt import Model, quicksum`.
- Create sparse variable dictionaries explicitly, for example:

```python
x = {(i, j, t): model.addVar(vtype="B", name=f"x[{i},{j},{t}]") for i, j, t in keys}
```

- Use `quicksum(...)` for large linear expressions.
- Use `model.addCons(expr <= rhs, name="capacity[k,t]")` for constraints.
- Use `model.setObjective(expr, "minimize")` or `model.setObjective(expr, "maximize")`.
- Set reproducibility and limits with SCIP parameters:

```python
model.setParam("limits/gap", 0.0005)
model.setParam("limits/time", time_limit)
model.setParam("display/verblevel", 0)
```

- After `model.optimize()`, inspect `model.getStatus()` and only read values if a solution exists.
- Read variable values with `model.getVal(x[key])`, not `x[key].X`.
- Read objective and bound with `model.getObjVal()` and `model.getDualbound()`.
- Read relative gap with `model.getGap()` when available.

## Modeling hygiene

- Calibrate every big-M from data. If a tight M is not obvious, derive a bound and document it in a short comment.
- Keep feasibility checks, objective recomputation, and reference-optimality comparison separate.
- Do not round exported decision values unless the schema explicitly requires it.
- For benchmark work, treat the evaluator or checker as the scoring authority and the reference solver as a validation baseline.
- Keep solver logs or a concise solve summary when the user needs auditability.
- Avoid changing data to make a model feasible unless the task is explicitly to design or repair an instance.

## Debugging boundaries

- If a model is infeasible, inspect hard lower bounds, conservation equations, and mutually exclusive binary logic before relaxing constraints.
- If objective values differ, recompute each objective component from exported decisions.
- If runtime is high, first remove dominated variables, tighten big-M values, add eligibility filters, and check whether binaries are really necessary.
- If SCIP returns an incumbent with a gap, say so clearly; do not call it exact optimality unless the status and gap support that claim.
- If an evaluator rejects a solution that the model considers feasible, replay the rejected rule directly from the exported file before changing solver code.

## Useful commands

```bash
python -c "import pyscipopt; print(pyscipopt.__version__)"
conda run -n or python -c "import pyscipopt; print(pyscipopt.__version__)"
<python-command> <solver-script.py>
<python-command> <checker-script.py> --solution <solution-file> --env-dir <task-dir>
```
