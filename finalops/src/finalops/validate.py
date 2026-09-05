from __future__ import annotations

import copy
from dataclasses import dataclass

import pulp


@dataclass
class ConstraintViolation:
    name: str
    slack: float  # negative slack means the constraint is violated by this much


@dataclass
class FeasibilityReport:
    feasible: bool
    violations: list[ConstraintViolation]


def _slack(constraint: pulp.LpConstraint) -> float:
    """Positive slack means the constraint has room to spare; negative means violated."""
    value = constraint.value()
    if constraint.sense == pulp.LpConstraintLE:
        return -value
    if constraint.sense == pulp.LpConstraintGE:
        return value
    return -abs(value)


def check_feasibility(model, tol: float = 1e-6) -> FeasibilityReport:
    """Recompute every constraint against the model's current variable values.
    Call this after solve() (or after manually setting varValue on a candidate
    solution) to get a structured, falsifiable answer instead of trusting that
    the code that built the model matched the intended rules.
    """
    violations = []
    for name, constraint in model.problem.constraints.items():
        slack = _slack(constraint)
        if slack < -tol:
            violations.append(ConstraintViolation(name=name, slack=slack))
    return FeasibilityReport(feasible=not violations, violations=violations)


def relaxation_bound(model, solver: pulp.LpSolver | None = None) -> float | None:
    """LP-relaxation bound: relax every integer/binary variable to continuous and
    resolve. This is the cheap, always-available substitute for a solver-reported
    best bound, used to give quality_gap() something to compare against.
    """
    relaxed = copy.deepcopy(model.problem)
    for var in relaxed.variables():
        var.cat = pulp.LpContinuous
    relaxed.solve(solver or pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[relaxed.status] != "Optimal":
        return None
    return pulp.value(relaxed.objective)


def quality_gap(model, incumbent_objective: float | None, solver: pulp.LpSolver | None = None) -> float | None:
    """Relative gap between the current candidate objective and the LP-relaxation
    bound. This is the signal agents currently lack mid-task: without it, 'runs
    and is feasible' looks indistinguishable from 'is actually good'.
    """
    if incumbent_objective is None:
        return None
    bound = relaxation_bound(model, solver=solver)
    if bound is None or bound == 0:
        return None
    return abs(incumbent_objective - bound) / abs(bound)
