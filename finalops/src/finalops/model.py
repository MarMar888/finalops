from __future__ import annotations

from collections.abc import Mapping

import pulp

from .ledger import DuplicateRequirementError, Ledger, RequirementKind
from .specs import Constraint, DataValue, DecisionVariable, LinearObjective, RuleViolation, Spec


class UntaggedConstraintError(ValueError):
    pass


class UnknownVariableError(ValueError):
    pass


class UnknownDataError(ValueError):
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
        self.variables: dict[str, pulp.LpVariable] = {}
        self.rules: list[Constraint] = []

    @classmethod
    def from_ledger(cls, ledger: Ledger, name: str = "model") -> "Model":
        """Build the whole model from what the ledger holds: create the variables,
        the objective and every rule, and link each to its requirement. The ledger's
        recorded links are rebuilt from scratch, so this is safe to call twice.
        """
        objectives = [r for r in ledger if isinstance(r.spec, LinearObjective)]
        if len(objectives) > 1:
            raise ValueError(f"a model has one objective, but the ledger defines {len(objectives)}: {', '.join(r.id for r in objectives)}")
        sense = pulp.LpMaximize if objectives and objectives[0].spec.sense == "max" else pulp.LpMinimize  # type: ignore[union-attr]

        ledger.reset_links()
        model = cls(name, ledger, sense)
        for req in ledger:
            if isinstance(req.spec, DecisionVariable):
                model.add_variable(req.spec.to_pulp(), requirement_id=req.id, units=req.spec.units)
        for req in objectives:
            model.set_objective(req.spec.compile(model), requirement_id=req.id)  # type: ignore[union-attr]
            model._link_data(req.spec)
        for req in ledger:
            if isinstance(req.spec, Constraint):
                model.add(req.spec)
        return model

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
        self.variables[var.name] = var
        self.ledger.mark_linked(requirement_id, constraint_name=var.name, expression=description)
        return var

    def var(self, name: str) -> pulp.LpVariable:
        """A declared variable, by name. A typo fails here, with the names that do exist."""
        try:
            return self.variables[name]
        except KeyError:
            known = ", ".join(sorted(self.variables)) or "(none yet)"
            raise UnknownVariableError(f"no variable named '{name}'. Declared variables: {known}") from None

    def quantity(self, value: float | str) -> float:
        """A number, or, if given an id, the value of that `data` requirement."""
        if not isinstance(value, str):
            return value
        if value in self.ledger:
            spec = self.ledger.get(value).spec
            if isinstance(spec, DataValue):
                return spec.value
        known = ", ".join(sorted(r.id for r in self.ledger if isinstance(r.spec, DataValue))) or "(none)"
        raise UnknownDataError(
            f"'{value}' isn't a data value in the ledger. Data ids: {known}. Add one with ledger.data('{value}', <value>, source=...)"
        )

    def _link_data(self, spec: Spec) -> None:
        for ref in sorted(spec.data_refs()):
            units = self.ledger.get(ref).units
            note = f"{self.quantity(ref):g}{f' {units}' if units else ''} (used by {spec.id})"
            self.ledger.mark_linked(ref, constraint_name="data", expression=note)

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

    def add(self, rule: Constraint) -> list[pulp.LpConstraint]:
        """Add a rule object. If its id isn't in the ledger yet it's registered there
        (the rule carries its own description, source and units); if it was registered
        earlier from the brief, the rule becomes its definition and links to it.
        """
        if any(existing.id == rule.id for existing in self.rules):
            raise ValueError(f"a rule with id '{rule.id}' was already added")
        if rule.id in self.ledger:
            req = self.ledger.get(rule.id)
            if req.kind != RequirementKind.CONSTRAINT:
                raise ValueError(f"'{rule.id}' is a {req.kind.value} in the ledger, not a constraint")
            if req.spec is None:
                req.spec = rule
            elif req.spec is not rule:
                raise DuplicateRequirementError(f"requirement '{rule.id}' already has a definition")
        else:
            self.ledger.constrain(rule)

        compiled = rule.compile(self)
        for index, constraint in enumerate(compiled, start=1):
            name = rule.id if len(compiled) == 1 else f"{rule.id}_{index}"
            self.add_constraint(constraint, requirement_id=rule.id, name=name)
        self._link_data(rule)
        self.rules.append(rule)
        return compiled

    def check_rules(self, values: Mapping[str, float | None]) -> list[RuleViolation]:
        """Test solved variable values against every rule object, each in its own
        terms rather than through the constraint sent to the solver.
        """
        return [violation for rule in self.rules for violation in rule.check(self, values)]

    def set_objective(self, expr: pulp.LpAffineExpression, requirement_id: str) -> None:
        self._require(requirement_id)
        self.problem += expr
        self.ledger.mark_linked(requirement_id, constraint_name="objective", expression=str(expr))

    def solve(self, solver: pulp.LpSolver | None = None):
        from .solve import solve as _solve

        return _solve(self, solver=solver)
