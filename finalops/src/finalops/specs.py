from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, Literal, Union

import pulp
from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from .model import Model

_TOL = 1e-6

# int stays int (so `3` reads as `3*x`, not `3.0*x` in the ledger's audit strings).
Finite = Union[int, Annotated[float, Field(allow_inf_nan=False)]]

# A number, or the id of a `data` requirement in the ledger whose value is used instead.
Quantity = Union[Finite, str]


@dataclass
class RuleViolation:
    rule_id: str
    message: str
    amount: float | None = None


def _refs(quantities: Iterable[Any]) -> set[str]:
    return {q for q in quantities if isinstance(q, str)}


class Spec(BaseModel):
    """Anything a ledger requirement can carry that compiles into part of the model.

    The requirement (id, source, units: what the brief said) and its math live in one
    object, so they can't drift apart. Unknown fields are rejected, so a typo in a
    parameter name fails loudly instead of being silently ignored.
    """

    model_config = ConfigDict(extra="forbid")

    KIND: ClassVar[str]
    _registry: ClassVar[dict[str, Any]] = {}

    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    description: str = ""
    units: str | None = None

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        Spec._registry[cls.__name__] = cls

    def data_refs(self) -> set[str]:
        return set()

    def to_dict(self) -> dict[str, Any]:
        return {"type": type(self).__name__, **self.model_dump()}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Spec:
        fields = dict(data)
        type_name = fields.pop("type", None)
        spec_cls = Spec._registry.get(type_name)
        if spec_cls is None:
            known = ", ".join(sorted(Spec._registry))
            raise ValueError(f"unknown spec type {type_name!r}; known types: {known}")
        return spec_cls(**fields)


class DecisionVariable(Spec):
    KIND: ClassVar[str] = "decision_variable"

    lower: Finite | None = 0
    upper: Finite | None = None
    category: Literal["Continuous", "Integer", "Binary"] = "Continuous"

    @field_validator("id")
    @classmethod
    def _id_is_a_variable_name(cls, value: str) -> str:
        if not value.isidentifier():
            raise ValueError("must be letters, digits and underscores (not starting with a digit): it becomes the solver variable name")
        return value

    def to_pulp(self) -> pulp.LpVariable:
        return pulp.LpVariable(self.id, lowBound=self.lower, upBound=self.upper, cat=self.category)


class DataValue(Spec):
    KIND: ClassVar[str] = "data"

    value: Finite


class LinearObjective(Spec):
    KIND: ClassVar[str] = "objective"

    sense: Literal["min", "max"]
    coefficients: dict[str, Quantity] = Field(min_length=1)

    def data_refs(self) -> set[str]:
        return _refs(self.coefficients.values())

    def compile(self, model: Model) -> pulp.LpAffineExpression:
        return pulp.lpSum(model.quantity(c) * model.var(v) for v, c in self.coefficients.items())


class Constraint(Spec, ABC):
    """Base class for rules. Subclass it for each kind of rule the brief can contain:
    fill in named parameters, and the class supplies the algebra (`compile`) and a
    plain-Python restatement of the rule to test the answer against (`check`).
    """

    KIND: ClassVar[str] = "constraint"

    @abstractmethod
    def compile(self, model: Model) -> list[pulp.LpConstraint]:
        """The rule as solver constraints."""

    @abstractmethod
    def check(self, model: Model, values: Mapping[str, float | None]) -> list[RuleViolation]:
        """Test a solved set of variable values against the rule as specified,
        independently of the constraint that was actually sent to the solver.
        """

    def _weighted_sum(self, model: Model, weights: Mapping[str, Quantity], values: Mapping[str, float | None]) -> float | RuleViolation:
        missing = [name for name in weights if values.get(name) is None]
        if missing:
            return RuleViolation(self.id, f"no solved value for {', '.join(missing)}")
        return sum(model.quantity(weight) * values[name] for name, weight in weights.items())  # type: ignore[operator]


def _unit(units: str | None) -> str:
    return f" {units}" if units else ""


class CapacityLimit(Constraint):
    """A resource that can't be used past a limit: sum(uses[v] * v) <= limit."""

    limit: Quantity
    uses: dict[str, Quantity] = Field(min_length=1)

    def data_refs(self) -> set[str]:
        return _refs([self.limit, *self.uses.values()])

    def compile(self, model: Model) -> list[pulp.LpConstraint]:
        used = pulp.lpSum(model.quantity(c) * model.var(v) for v, c in self.uses.items())
        return [used <= model.quantity(self.limit)]

    def check(self, model: Model, values: Mapping[str, float | None]) -> list[RuleViolation]:
        used = self._weighted_sum(model, self.uses, values)
        if isinstance(used, RuleViolation):
            return [used]
        limit = model.quantity(self.limit)
        if used > limit + _TOL:
            return [RuleViolation(self.id, f"uses {used:g}{_unit(self.units)} against a limit of {limit:g}", used - limit)]
        return []


class DemandCoverage(Constraint):
    """Demand that has to be met: sum(covered_by[v] * v) >= required.
    `covered_by` can be a plain list of variable ids when each counts once.
    """

    required: Quantity
    covered_by: dict[str, Quantity] = Field(min_length=1)

    @field_validator("covered_by", mode="before")
    @classmethod
    def _list_means_one_each(cls, value: Any) -> Any:
        if isinstance(value, (list, tuple)):
            return {name: 1 for name in value}
        return value

    def data_refs(self) -> set[str]:
        return _refs([self.required, *self.covered_by.values()])

    def compile(self, model: Model) -> list[pulp.LpConstraint]:
        provided = pulp.lpSum(model.quantity(c) * model.var(v) for v, c in self.covered_by.items())
        return [provided >= model.quantity(self.required)]

    def check(self, model: Model, values: Mapping[str, float | None]) -> list[RuleViolation]:
        provided = self._weighted_sum(model, self.covered_by, values)
        if isinstance(provided, RuleViolation):
            return [provided]
        required = model.quantity(self.required)
        if provided < required - _TOL:
            return [RuleViolation(self.id, f"covers {provided:g}{_unit(self.units)} of the {required:g} required", required - provided)]
        return []


class CustomConstraint(Constraint):
    """The escape hatch, for a rule none of the classes above express.

    `build` receives the model and returns a PuLP constraint (or a list of them), so it can
    be written before the variables exist: `lambda m: m.var("a") <= 2 * m.var("b")`. `check`
    is optional; without it the rule is only enforced, not independently tested. Because it
    holds a function, a ledger containing one can't be saved to JSON.
    """

    build: Callable[..., Any]
    check_fn: Callable[..., Any] | None = None

    def compile(self, model: Model) -> list[pulp.LpConstraint]:
        built = self.build(model)
        constraints = list(built) if isinstance(built, (list, tuple)) else [built]
        for c in constraints:
            if not isinstance(c, pulp.LpConstraint):
                raise TypeError(
                    f"rule '{self.id}': build() must return a PuLP constraint (or a list of them), got {type(c).__name__}. "
                    "A comparison between two plain numbers evaluates to a bool, not a constraint."
                )
        return constraints

    def check(self, model: Model, values: Mapping[str, float | None]) -> list[RuleViolation]:
        return list(self.check_fn(model, values)) if self.check_fn else []

    def to_dict(self) -> dict[str, Any]:
        raise TypeError(f"rule '{self.id}' is a CustomConstraint: it holds a function, so it can't be saved to JSON")
