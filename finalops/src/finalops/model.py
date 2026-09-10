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
        self.requirement_by_variable: dict[str, str] = {}

    def _require(self, requirement_id: str) -> None:
        if requirement_id not in self.ledger:
            raise UntaggedConstraintError(
                f"'{requirement_id}' is not in the ledger. Call ledger.add(id='{requirement_id}', "
                "description=..., source=...) before wiring it into the model."
            )

    def add_variable(
        self,
        var: pulp.LpVariable,
        requirement_id: str,
        units: str | None = None,
    ) -> pulp.LpVariable:
        """Register a decision variable against the ledger requirement it answers
        (e.g. "how many hours per week does process A run"). `units` is stored
        explicitly because PuLP variables have no unit concept of their own, and
        a dropped or mismatched unit is exactly the kind of silent error the
        ledger exists to surface.
        """
        self._require(requirement_id)
        low = "-inf" if var.lowBound is None else var.lowBound
        high = "+inf" if var.upBound is None else var.upBound
        description = f"{var.cat} variable, bounds=[{low}, {high}]"
        if units:
            description += f", units={units}"
        self.requirement_by_variable[var.name] = requirement_id
        self.ledger.mark_linked(requirement_id, constraint_name=var.name, expression=description)
        return var

    def cite_data(self, requirement_id: str, note: str) -> None:
        """Record that a hard number (a bound, a coefficient) tracked in the
        ledger as DATA was actually used, and what it was — e.g.
        `cite_data("unit_cost", "3.0 $/unit, from data/costs.csv")`. Data has no
        PuLP object to attach to the way a constraint or variable does, so this
        is the explicit citation that stands in for one.
        """
        self._require(requirement_id)
        self.ledger.mark_linked(requirement_id, constraint_name="data", expression=note)

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
