from __future__ import annotations

from dataclasses import dataclass

import pulp


@dataclass
class RequirementViolation:
    constraint_name: str
    requirement_id: str | None
    description: str | None
    magnitude: float


@dataclass
class InfeasibilityDiagnosis:
    feasible: bool
    violations: list[RequirementViolation]


def explain_infeasibility(
    model,
    solver: pulp.LpSolver | None = None,
    tol: float = 1e-6,
) -> InfeasibilityDiagnosis:
    """When the model is infeasible, don't stop at the word 'Infeasible': relax
    every constraint with a penalized slack/surplus variable, resolve to
    minimize total violation, and report which constraints — and which ledger
    requirements — are responsible, and by how much.

    This is a deletion-free stand-in for an IIS (irreducible infeasible
    subsystem). Open-source solvers exposed through PuLP (CBC, HiGHS) don't
    ship one; only some commercial solvers do. Minimizing total elastic
    violation is solver-agnostic and, unlike a bare IIS, also reports
    magnitude — which is directly actionable ("relax capacity by 12 units"),
    not just "these constraints are jointly unsatisfiable."
    """
    relaxed = pulp.LpProblem(f"{model.name}__elastic", pulp.LpMinimize)
    penalty_terms: list[pulp.LpVariable] = []
    slack_vars: dict[str, list[pulp.LpVariable]] = {}

    for name, constraint in model.problem.constraints.items():
        expr = pulp.lpSum(coef * var for var, coef in constraint.items())
        rhs = -constraint.constant

        if constraint.sense == pulp.LpConstraintLE:
            surplus = pulp.LpVariable(f"_slack_{name}_over", lowBound=0)
            relaxed += (expr - surplus <= rhs), name
            slack_vars[name] = [surplus]
        elif constraint.sense == pulp.LpConstraintGE:
            surplus = pulp.LpVariable(f"_slack_{name}_under", lowBound=0)
            relaxed += (expr + surplus >= rhs), name
            slack_vars[name] = [surplus]
        else:
            pos = pulp.LpVariable(f"_slack_{name}_pos", lowBound=0)
            neg = pulp.LpVariable(f"_slack_{name}_neg", lowBound=0)
            relaxed += (expr + pos - neg == rhs), name
            slack_vars[name] = [pos, neg]

        penalty_terms.extend(slack_vars[name])

    relaxed += pulp.lpSum(penalty_terms)
    relaxed.solve(solver or pulp.PULP_CBC_CMD(msg=False))

    violations = []
    for name, vars_ in slack_vars.items():
        magnitude = sum(v.varValue or 0.0 for v in vars_)
        if magnitude > tol:
            requirement_id = model.requirement_by_constraint.get(name)
            description = (
                model.ledger.get(requirement_id).description
                if requirement_id and requirement_id in model.ledger
                else None
            )
            violations.append(
                RequirementViolation(
                    constraint_name=name,
                    requirement_id=requirement_id,
                    description=description,
                    magnitude=magnitude,
                )
            )

    violations.sort(key=lambda v: v.magnitude, reverse=True)
    return InfeasibilityDiagnosis(feasible=not violations, violations=violations)
