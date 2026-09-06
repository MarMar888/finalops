from __future__ import annotations

import copy
from dataclasses import dataclass

import pulp

from .validate import _slack

_BINDING_TOL = 1e-6


@dataclass
class RequirementSensitivity:
    requirement_id: str
    binding: bool
    slack: float
    shadow_price: float | None
    basis: str  # "exact" | "lp_relaxation" | "unavailable"


@dataclass
class SensitivityReport:
    model: str
    basis: str
    requirements: list[RequirementSensitivity]


@dataclass
class ImpactResult:
    requirement_id: str
    change: str
    objective_before: float | None
    objective_after: float | None
    objective_delta: float | None
    feasible_after: bool
    binding_flips: list[str]


@dataclass
class SolveDiff:
    objective_delta: float | None
    binding_flips: list[str]
    variable_deltas: dict[str, float]
    feasibility_changed: bool


def _requirement_id_by_constraint_name(model) -> dict[str, str]:
    """Constraints are stored on pulp.LpProblem keyed by their (possibly
    mangled) name. Model.add_constraint sets constraint.name to the
    requirement_id, so this is a straight lookup rather than a guess.
    """
    return {name: con.name for name, con in model.problem.constraints.items() if con.name}


def _is_mip(model) -> bool:
    return any(v.cat != pulp.LpContinuous for v in model.problem.variables())


def binding_report(model) -> SensitivityReport:
    """For every constraint (== ledger requirement), report slack, whether
    it's binding, and its shadow price. Duals are only exact for continuous
    LPs; for a MIP they're computed against the LP relaxation instead of
    silently printing a misleading number, and every entry is tagged with
    which basis produced it.
    """
    mip = _is_mip(model)
    basis = "lp_relaxation" if mip else "exact"

    dual_source = model
    if mip:
        dual_source = _relaxed_clone(model)
        dual_source.problem.solve(pulp.PULP_CBC_CMD(msg=False))

    requirements = []
    for name, constraint in model.problem.constraints.items():
        req_id = constraint.name or name
        slack = _slack(constraint)
        binding = abs(slack) <= _BINDING_TOL

        dual_constraint = dual_source.problem.constraints.get(name)
        shadow_price = dual_constraint.pi if dual_constraint is not None else None
        entry_basis = basis if shadow_price is not None else "unavailable"

        requirements.append(
            RequirementSensitivity(
                requirement_id=req_id,
                binding=binding,
                slack=slack,
                shadow_price=shadow_price,
                basis=entry_basis,
            )
        )

    return SensitivityReport(model=model.name, basis=basis, requirements=requirements)


def _relaxed_clone(model):
    """A deepcopy of model with every integer/binary variable relaxed to
    continuous, used to source shadow prices for MIP problems. Mirrors
    validate.relaxation_bound's approach.
    """
    clone = copy.copy(model)
    clone.problem = copy.deepcopy(model.problem)
    for var in clone.problem.variables():
        var.cat = pulp.LpContinuous
    return clone


def _clone_with_constraint(model, requirement_id: str, *, drop: bool = False, rhs_delta: float = 0.0):
    """A deepcopy of model with one constraint (identified by requirement_id)
    either dropped or RHS-shifted by rhs_delta. Used for what-if re-solves —
    exact for any model type (LP or MIP), unlike shadow prices.
    """
    clone = copy.copy(model)
    clone.problem = copy.deepcopy(model.problem)

    target_name = None
    for name, constraint in clone.problem.constraints.items():
        if constraint.name == requirement_id or name == requirement_id:
            target_name = name
            break

    if target_name is None:
        raise KeyError(f"no constraint found for requirement '{requirement_id}'")

    if drop:
        del clone.problem.constraints[target_name]
    else:
        clone.problem.constraints[target_name].constant -= rhs_delta

    return clone


def requirement_impact(
    model,
    requirement_id: str,
    *,
    drop: bool = False,
    rhs_delta: float = 0.0,
    solver: pulp.LpSolver | None = None,
) -> ImpactResult:
    """What-if: relax/tighten a single requirement's constraint by rhs_delta,
    or drop it entirely, re-solve, and report what changed. A brute-force
    re-solve rather than analytic ranging, so it's correct for MIPs too, not
    just LPs — the tradeoff is one extra solve per question asked.
    """
    before_report = binding_report(model)
    objective_before = pulp.value(model.problem.objective)

    change = "dropped" if drop else f"RHS shifted by {rhs_delta:+g}"
    clone = _clone_with_constraint(model, requirement_id, drop=drop, rhs_delta=rhs_delta)

    solver = solver or pulp.PULP_CBC_CMD(msg=False)
    clone.problem.solve(solver)
    status = pulp.LpStatus[clone.problem.status]
    objective_after = pulp.value(clone.problem.objective) if status == "Optimal" else None

    objective_delta = None
    if objective_before is not None and objective_after is not None:
        objective_delta = objective_after - objective_before

    binding_flips: list[str] = []
    if status == "Optimal":
        after_report = binding_report(clone)
        before_binding = {r.requirement_id: r.binding for r in before_report.requirements}
        binding_flips = [
            r.requirement_id
            for r in after_report.requirements
            if r.requirement_id in before_binding and before_binding[r.requirement_id] != r.binding
        ]

    return ImpactResult(
        requirement_id=requirement_id,
        change=change,
        objective_before=objective_before,
        objective_after=objective_after,
        objective_delta=objective_delta,
        feasible_after=status == "Optimal",
        binding_flips=binding_flips,
    )


def solve_diff(before_result, after_result, before_report=None, after_report=None) -> SolveDiff:
    """Compare two SolveResult snapshots — e.g. the model before and after a
    hand-edited constraint — and report what shifted. General case of
    requirement_impact for when more than one thing changed between two
    versions of a model.

    Pass the matching binding_report() output for each side (before_report/
    after_report) to also get binding_flips; without them that field is
    just left empty rather than guessed at.
    """
    objective_delta = None
    if before_result.objective is not None and after_result.objective is not None:
        objective_delta = after_result.objective - before_result.objective

    variable_deltas = {}
    all_names = set(before_result.variables) | set(after_result.variables)
    for name in all_names:
        b = before_result.variables.get(name)
        a = after_result.variables.get(name)
        if b is None or a is None:
            continue
        delta = a - b
        if abs(delta) > _BINDING_TOL:
            variable_deltas[name] = delta

    feasibility_changed = (before_result.status == "Optimal") != (after_result.status == "Optimal")

    binding_flips: list[str] = []
    if before_report is not None and after_report is not None:
        before_binding = {r.requirement_id: r.binding for r in before_report.requirements}
        for r in after_report.requirements:
            if r.requirement_id in before_binding and before_binding[r.requirement_id] != r.binding:
                binding_flips.append(r.requirement_id)

    return SolveDiff(
        objective_delta=objective_delta,
        binding_flips=binding_flips,
        variable_deltas=variable_deltas,
        feasibility_changed=feasibility_changed,
    )
