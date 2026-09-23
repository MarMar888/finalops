from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .specs import Constraint, DataValue, DecisionVariable, LinearObjective, Quantity, Spec


class RequirementKind(str, Enum):
    """The four things a brief has to be decomposed into before any solver code
    gets written, in the order a modeler would normally work through them:
    what can be chosen (DECISION_VARIABLE), what "good" means
    (OBJECTIVE), what's not allowed (CONSTRAINT), and what hard numbers
    everything above is built from (DATA).
    """

    DECISION_VARIABLE = "decision_variable"
    OBJECTIVE = "objective"
    CONSTRAINT = "constraint"
    DATA = "data"


@dataclass
class LinkedConstraint:
    """One concrete constraint (or the objective) wired up in the model in
    fulfillment of a ledger requirement, and its expression at link time —
    the "how" behind a linked requirement, not just the fact that it happened.
    """

    name: str
    expression: str


@dataclass
class Requirement:
    id: str
    description: str
    source: str
    kind: RequirementKind = RequirementKind.CONSTRAINT
    units: str | None = None
    linked_constraints: list[LinkedConstraint] = field(default_factory=list)
    spec: Spec | None = None

    @property
    def linked(self) -> bool:
        return bool(self.linked_constraints)


class DuplicateRequirementError(ValueError):
    pass


class Ledger:
    """The checklist-first artifact: every operational rule pulled from the brief
    gets registered here, with where it came from, before any model code is written.
    Constraints wired up later must cite a requirement id, so a rule that never
    makes it into the model shows up as an unlinked entry instead of silently
    disappearing — and each link records which constraint (or the objective)
    fulfilled it, and its expression, so "linked" is auditable, not just a flag.
    """

    def __init__(self, requirements: list[Requirement] | None = None):
        self._by_id: dict[str, Requirement] = {}
        for req in requirements or []:
            self._by_id[req.id] = req

    def add(
        self,
        id: str,
        description: str,
        source: str,
        kind: RequirementKind | str = RequirementKind.CONSTRAINT,
        units: str | None = None,
    ) -> Requirement:
        if id in self._by_id:
            raise DuplicateRequirementError(f"requirement '{id}' already exists")
        req = Requirement(id=id, description=description, source=source, kind=RequirementKind(kind), units=units)
        self._by_id[id] = req
        return req

    def get(self, id: str) -> Requirement:
        return self._by_id[id]

    def __contains__(self, id: str) -> bool:
        return id in self._by_id

    def __iter__(self):
        return iter(self._by_id.values())

    def __len__(self) -> int:
        return len(self._by_id)

    def mark_linked(self, id: str, constraint_name: str, expression: str) -> None:
        if id not in self._by_id:
            raise KeyError(
                f"requirement '{id}' is not in the ledger — add it with ledger.add(...) "
                "before wiring it into a constraint"
            )
        self._by_id[id].linked_constraints.append(LinkedConstraint(name=constraint_name, expression=expression))

    def unlinked(self) -> list[Requirement]:
        return [r for r in self._by_id.values() if not r.linked]

    def reset_links(self) -> None:
        """Forget every recorded link, so a model can be built from the ledger afresh."""
        for req in self._by_id.values():
            req.linked_constraints.clear()

    def _attach(self, spec: Spec) -> Requirement:
        """Put a spec in the ledger: as a new requirement, or onto one already
        registered from the brief (so 'write the checklist first' still works).
        """
        kind = RequirementKind(spec.KIND)
        existing = self._by_id.get(spec.id)
        if existing is None:
            req = self.add(id=spec.id, description=spec.description or spec.id, source=spec.source, kind=kind, units=spec.units)
        else:
            if existing.kind != kind:
                raise ValueError(f"requirement '{spec.id}' is registered as {existing.kind.value}, but this is a {kind.value}")
            if existing.spec is not None:
                raise DuplicateRequirementError(f"requirement '{spec.id}' already has a definition")
            req = existing
        req.spec = spec
        return req

    def variable(
        self,
        id: str,
        *,
        source: str,
        description: str = "",
        units: str | None = None,
        lower: float | None = 0,
        upper: float | None = None,
        category: str = "Continuous",
    ) -> Requirement:
        """A decision variable: something the model gets to choose."""
        return self._attach(
            DecisionVariable(id=id, source=source, description=description, units=units, lower=lower, upper=upper, category=category)  # type: ignore[arg-type]
        )

    def data(self, id: str, value: float, *, source: str, units: str | None = None, description: str = "") -> Requirement:
        """A hard number. Rules refer to it by id, so the number carries its units and
        source with it and shows up as unlinked if nothing ever uses it.
        """
        return self._attach(DataValue(id=id, value=value, source=source, units=units, description=description))

    def minimize(
        self, id: str, coefficients: Mapping[str, Quantity], *, source: str, description: str = "", units: str | None = None
    ) -> Requirement:
        """The objective, as a cost per variable. A coefficient is a number or a data id."""
        return self._attach(
            LinearObjective(id=id, sense="min", coefficients=dict(coefficients), source=source, description=description, units=units)
        )

    def maximize(
        self, id: str, coefficients: Mapping[str, Quantity], *, source: str, description: str = "", units: str | None = None
    ) -> Requirement:
        return self._attach(
            LinearObjective(id=id, sense="max", coefficients=dict(coefficients), source=source, description=description, units=units)
        )

    def constrain(self, rule: Constraint) -> Requirement:
        """A rule from the brief, as a Constraint object (CapacityLimit, DemandCoverage, ...)."""
        if not isinstance(rule, Constraint):
            raise TypeError(f"expected a Constraint (e.g. CapacityLimit), got {type(rule).__name__}")
        return self._attach(rule)

    def to_json(self, path: str | Path) -> None:
        data = []
        for r in self._by_id.values():
            data.append(
                {
                    "id": r.id,
                    "description": r.description,
                    "source": r.source,
                    "kind": r.kind.value,
                    "units": r.units,
                    "linked_constraints": [{"name": lc.name, "expression": lc.expression} for lc in r.linked_constraints],
                    "linked": r.linked,
                    "spec": r.spec.to_dict() if r.spec is not None else None,
                }
            )
        Path(path).write_text(json.dumps(data, indent=2) + "\n")

    @classmethod
    def from_json(cls, path: str | Path) -> "Ledger":
        raw = Path(path).read_text().strip()
        data = json.loads(raw) if raw else []
        reqs = [
            Requirement(
                id=d["id"],
                description=d["description"],
                source=d["source"],
                kind=RequirementKind(d.get("kind", "constraint")),
                units=d.get("units"),
                linked_constraints=[
                    LinkedConstraint(name=lc["name"], expression=lc["expression"])
                    for lc in d.get("linked_constraints", [])
                ],
                spec=Spec.from_dict(d["spec"]) if d.get("spec") else None,
            )
            for d in data
        ]
        return cls(reqs)
