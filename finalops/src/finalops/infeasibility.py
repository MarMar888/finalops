from __future__ import annotations

import copy
from collections import OrderedDict
from dataclasses import dataclass, field

import pulp


@dataclass
class RequirementViolation:
    constraint_name: str
    requirement_id: str | None
    description: str | None
    magnitude: float


@dataclass
class ConflictMember:
    """One piece of an irreducible infeasible subset: a constraint, or one side of a
    variable's bounds."""

    kind: str  # "constraint" | "bound"
    name: str  # the constraint's name, or the variable's name for a bound
    expression: str
    requirement_id: str | None = None
    description: str | None = None
    bound: str | None = None  # "lower" | "upper" when kind == "bound"


@dataclass
class Conflict:
    """A set of rules that can't all hold, from which removing any one member makes the
    rest satisfiable (when `minimal`). `solves` is how many LP solves it took to find it.
    """

    members: list[ConflictMember]
    minimal: bool
    solves: int
    requirement_ids: list[str] = field(default_factory=list)


@dataclass
class InfeasibilityDiagnosis:
    feasible: bool
    violations: list[RequirementViolation]
    conflict: Conflict | None = None


def find_conflict(
    model,
    solver: pulp.LpSolver | None = None,
    max_solves: int = 200,
) -> Conflict | None:
    """Find an irreducible infeasible subset (IIS): a set of constraints and variable
    bounds that can't all hold, where removing any single one of them makes the rest
    satisfiable. Returns None if the model as a whole isn't infeasible.

    CBC and HiGHS don't ship an IIS finder, so this is a deletion filter: start with
    everything, try dropping items (in chunks, halving the chunk size, so a big model
    doesn't cost one solve per item), and keep a drop whenever what's left is still
    infeasible. Whatever survives the final one-at-a-time pass is minimal. Variable
    integrality is left in place throughout, and each solve checks feasibility only.

    If `max_solves` runs out first, the subset found so far is returned with
    `minimal=False`: still a real conflict, just possibly bigger than it needs to be.
    """
    solver = solver or pulp.PULP_CBC_CMD(msg=False)
    source = copy.deepcopy(model.problem)
    all_constraints = OrderedDict(source.constraints)
    variables = {var.name: var for var in source.variables()}
    bounds = {name: (var.lowBound, var.upBound) for name, var in variables.items()}

    # Bounds go first so a plain x >= 0 gets dropped when the constraints alone conflict.
    items: list[tuple[str, str]] = []
    for name, (lower, upper) in bounds.items():
        if lower is not None:
            items.append(("lower", name))
        if upper is not None:
            items.append(("upper", name))
    items.extend(("constraint", name) for name in all_constraints)

    solves = 0

    def infeasible(keep: set[tuple[str, str]]) -> bool:
        nonlocal solves
        if not any(kind == "constraint" for kind, _ in keep):
            return False
        for name, var in variables.items():
            lower, upper = bounds[name]
            var.lowBound = lower if ("lower", name) in keep else None
            var.upBound = upper if ("upper", name) in keep else None
        # A fresh problem each time: PuLP keeps every variable it has ever seen in a
        # problem, and hands the solver ones that no longer appear in any constraint.
        trial = pulp.LpProblem("conflict", pulp.LpMinimize)
        for n, c in all_constraints.items():
            if ("constraint", n) in keep:
                trial.addConstraint(c, n)
        solves += 1
        trial.solve(solver)
        return pulp.LpStatus[trial.status] == "Infeasible"

    if not infeasible(set(items)):
        return None

    core = list(items)
    minimal = True
    chunk = max(1, len(core) // 2)
    while minimal:
        i = 0
        while i < len(core):
            if solves >= max_solves:
                minimal = False
                break
            trial = core[:i] + core[i + chunk :]
            if infeasible(set(trial)):
                core = trial
            else:
                i += chunk
        if chunk == 1:
            break
        chunk //= 2

    members = [_member(model, all_constraints, kind, name, bounds) for kind, name in core]
    requirement_ids = list(dict.fromkeys(m.requirement_id for m in members if m.requirement_id))
    return Conflict(members=members, minimal=minimal, solves=solves, requirement_ids=requirement_ids)


def _member(model, constraints, kind: str, name: str, bounds) -> ConflictMember:
    if kind == "constraint":
        requirement_id = model.requirement_by_constraint.get(name)
        expression = str(constraints[name])
        side = None
    else:
        requirement_id = model.requirement_by_variable.get(name)
        lower, upper = bounds[name]
        expression = f"{name} >= {lower:g}" if kind == "lower" else f"{name} <= {upper:g}"
        side = kind
    description = (
        model.ledger.get(requirement_id).description if requirement_id and requirement_id in model.ledger else None
    )
    return ConflictMember(
        kind="constraint" if kind == "constraint" else "bound",
        name=name,
        expression=expression,
        requirement_id=requirement_id,
        description=description,
        bound=side,
    )


def explain_infeasibility(
    model,
    solver: pulp.LpSolver | None = None,
    tol: float = 1e-6,
    max_conflict_solves: int = 200,
) -> InfeasibilityDiagnosis:
    """When the model is infeasible, don't stop at the word 'Infeasible'. Returns two
    complementary answers, both tied back to ledger requirements:

    - `conflict`: an irreducible set of rules that can't all hold (see `find_conflict`).
      Dropping or loosening any one of them makes the rest satisfiable.
    - `violations`: relax every constraint with a penalized slack/surplus variable and
      minimize total violation. This says how far to move, which is what turns "these
      conflict" into "relax capacity by 12 units". It is not minimal in the IIS sense:
      the constraints it names are one cheap way out, not the whole conflict.
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
    conflict = find_conflict(model, solver=solver, max_solves=max_conflict_solves) if violations else None
    return InfeasibilityDiagnosis(feasible=not violations, violations=violations, conflict=conflict)
