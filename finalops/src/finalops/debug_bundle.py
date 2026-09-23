from __future__ import annotations

import copy
import json
from dataclasses import asdict
from pathlib import Path

import pulp

from .cbc_diagnostics import solve_with_diagnostics
from .infeasibility import explain_infeasibility
from .ledger import Ledger
from .model import Model
from .report import build_report, diagnose
from .sensitivity import binding_report
from .validate import _slack

SCHEMA_VERSION = 1

_SENSE = {pulp.LpConstraintLE: "<=", pulp.LpConstraintGE: ">=", pulp.LpConstraintEQ: "=="}


def _terms(expr) -> dict[str, float]:
    return {var.name: coef for var, coef in expr.items()}


def _objective_requirement_id(model) -> str | None:
    for req in model.ledger:
        if any(lc.name == "objective" for lc in req.linked_constraints):
            return req.id
    return None


def _solve_without(model, constraint_name: str) -> dict:
    """Re-solve with one constraint deleted. Unlike requirement_impact, this works on
    an infeasible model too, which is exactly when 'which single rule, dropped, makes
    it solvable?' is the question being asked.
    """
    clone = copy.deepcopy(model.problem)
    del clone.constraints[constraint_name]
    clone.solve(pulp.PULP_CBC_CMD(msg=False))
    status = pulp.LpStatus[clone.status]
    objective = pulp.value(clone.objective) if status == "Optimal" and clone.objective is not None else None
    return {"status": status, "objective": objective}


def build_debug_bundle(
    model,
    out: str | Path | None = None,
    *,
    time_limit: float | None = None,
    max_gap: float = 0.05,
    include_what_if: bool = True,
    max_what_if_constraints: int = 100,
    name: str = "model",
) -> dict:
    """Solve the model and gather everything a viewer needs to explain the result into
    one JSON-serializable dict: the ledger, every variable and constraint with its
    slack / shadow price / requirement, the objective, the solver's bound, and either
    the infeasibility diagnosis or the binding constraints. Written to `out` if given.

    With include_what_if, each constraint is also dropped and the model re-solved, so a
    static viewer can answer "what if I removed this rule?" without a live backend. That
    is one extra solve per constraint, so it's skipped past max_what_if_constraints.
    """
    if isinstance(model, Ledger):
        model = Model.from_ledger(model, name=name)
    result, diagnostics = solve_with_diagnostics(model, time_limit=time_limit)
    infeasibility = explain_infeasibility(model) if result.status == "Infeasible" else None
    report = build_report(
        model,
        result,
        bound=diagnostics.bound,
        proven_optimal=diagnostics.proven_optimal,
        infeasibility=infeasibility,
    )
    problems = diagnose(report, max_gap=max_gap)

    # Solver-returned values are only meaningful for an optimal (or time-limited
    # incumbent) solve; for infeasible/unbounded they're arbitrary and would mislead.
    has_solution = result.status == "Optimal"

    constraint_names = list(model.problem.constraints.keys())
    sensitivity = binding_report(model).requirements if has_solution else []
    violation_by_name = {v.constraint_name: v.magnitude for v in infeasibility.violations} if infeasibility else {}
    conflict_names = {m.name for m in infeasibility.conflict.members if m.kind == "constraint"} if infeasibility and infeasibility.conflict else set()
    run_what_if = include_what_if and len(constraint_names) <= max_what_if_constraints

    constraints = []
    for index, (name, constraint) in enumerate(model.problem.constraints.items()):
        slack = _slack(constraint) + 0.0 if has_solution else None
        sens = sensitivity[index] if has_solution else None
        constraints.append(
            {
                "name": name,
                "requirement_id": model.requirement_by_constraint.get(name),
                "expression": str(constraint),
                "sense": _SENSE[constraint.sense],
                "rhs": -constraint.constant,
                "terms": _terms(constraint),
                "slack": slack,
                "binding": sens.binding if sens else None,
                "shadow_price": (sens.shadow_price + 0.0) if sens and sens.shadow_price is not None else None,
                "shadow_basis": sens.basis if sens else None,
                "violation": violation_by_name.get(name),
                "in_conflict": (name in conflict_names) if infeasibility is not None else None,
                "what_if_dropped": _solve_without(model, name) if run_what_if else None,
            }
        )

    variables = []
    for var in model.problem.variables():
        requirement_id = model.requirement_by_variable.get(var.name)
        requirement = model.ledger.get(requirement_id) if requirement_id in model.ledger else None
        # PuLP stores Binary as Integer with bounds [0, 1]; show it the way it was declared.
        is_binary = var.cat == pulp.LpInteger and var.lowBound == 0 and var.upBound == 1
        variables.append(
            {
                "name": var.name,
                "value": var.varValue if has_solution else None,
                "lower": var.lowBound,
                "upper": var.upBound,
                "category": "Binary" if is_binary else var.cat,
                "requirement_id": requirement_id,
                "units": requirement.units if requirement else None,
            }
        )

    objective = model.problem.objective
    bundle = {
        "schema_version": SCHEMA_VERSION,
        "model": model.name,
        "summary": {
            "status": result.status,
            "termination": diagnostics.result_line,
            "sense": "max" if model.problem.sense == pulp.LpMaximize else "min",
            "objective": result.objective if has_solution else None,
            "bound": diagnostics.bound,
            "proven_optimal": diagnostics.proven_optimal,
            "quality_gap": report["quality_gap"],
            "feasible": report["feasible"],
            "problems": problems,
            "unlinked_requirements": report["unlinked_requirements"],
        },
        "requirements": [
            {
                "id": req.id,
                "kind": req.kind.value,
                "description": req.description,
                "source": req.source,
                "units": req.units,
                "linked": [asdict(lc) for lc in req.linked_constraints],
            }
            for req in model.ledger
        ],
        "variables": variables,
        "constraints": constraints,
        "objective": {
            "requirement_id": _objective_requirement_id(model),
            "expression": str(objective) if objective is not None else None,
            "terms": _terms(objective) if objective is not None else {},
        },
        "infeasibility": (
            {
                "violations": [asdict(v) for v in infeasibility.violations],
                "conflict": asdict(infeasibility.conflict) if infeasibility.conflict else None,
            }
            if infeasibility is not None
            else None
        ),
    }

    if out:
        Path(out).write_text(json.dumps(bundle, indent=2) + "\n")

    return bundle
