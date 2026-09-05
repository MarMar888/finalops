from __future__ import annotations

from dataclasses import dataclass

import pulp


@dataclass
class SolveResult:
    status: str
    objective: float | None
    variables: dict[str, float]


def solve(model, solver: pulp.LpSolver | None = None) -> SolveResult:
    solver = solver or pulp.PULP_CBC_CMD(msg=False)
    model.problem.solve(solver)
    status = pulp.LpStatus[model.problem.status]
    objective = pulp.value(model.problem.objective)
    variables = {v.name: v.varValue for v in model.problem.variables()}
    return SolveResult(status=status, objective=objective, variables=variables)
