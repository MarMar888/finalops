from __future__ import annotations

import pulp

from .ledger import Ledger


class UntaggedConstraintError(ValueError):
    pass


class Model:
    """Thin wrapper around pulp.LpProblem that forces every constraint and the
    objective to cite a ledger requirement id. It doesn't add any modeling
    power PuLP doesn't already have — the point is that a rule the agent forgot
    to add to the ledger, or a constraint it forgot to wire up, fails loudly
    and immediately instead of silently missing from the formulation.
    """

    def __init__(self, name: str, ledger: Ledger, sense: int = pulp.LpMinimize):
        self.name = name
        self.ledger = ledger
        self.problem = pulp.LpProblem(name, sense)
        self.requirement_by_constraint: dict[str, str] = {}

    def _require(self, requirement_id: str) -> None:
        if requirement_id not in self.ledger:
            raise UntaggedConstraintError(
                f"'{requirement_id}' is not in the ledger. Call ledger.add(id='{requirement_id}', "
                "description=..., source=...) before wiring it into the model."
            )

    def add_constraint(
        self,
        constraint: pulp.LpConstraint,
        requirement_id: str,
        name: str | None = None,
    ) -> pulp.LpConstraint:
        self._require(requirement_id)
        # Assign the name ourselves (rather than letting PuLP auto-generate one on
        # `+=`) so we reliably know the key to look up later when explaining an
        # infeasibility back to the ledger requirement that produced it.
        constraint.name = name or f"c{len(self.problem.constraints) + 1}"
        self.problem += constraint
        self.requirement_by_constraint[constraint.name] = requirement_id
        self.ledger.mark_linked(requirement_id, constraint_name=constraint.name, expression=str(constraint))
        return constraint

    def set_objective(self, expr: pulp.LpAffineExpression, requirement_id: str) -> None:
        self._require(requirement_id)
        self.problem += expr
        self.ledger.mark_linked(requirement_id, constraint_name="objective", expression=str(expr))

    def solve(self, solver: pulp.LpSolver | None = None):
        from .solve import solve as _solve

        return _solve(self, solver=solver)
