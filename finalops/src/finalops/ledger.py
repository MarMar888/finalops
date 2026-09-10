from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path


class RequirementKind(str, Enum):
    CONSTRAINT = "constraint"
    OBJECTIVE = "objective"
    RESOURCE = "resource"


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
    linked_constraints: list[LinkedConstraint] = field(default_factory=list)

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
    ) -> Requirement:
        if id in self._by_id:
            raise DuplicateRequirementError(f"requirement '{id}' already exists")
        req = Requirement(id=id, description=description, source=source, kind=RequirementKind(kind))
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

    def to_json(self, path: str | Path) -> None:
        data = []
        for r in self._by_id.values():
            payload = asdict(r)
            payload["kind"] = r.kind.value
            payload["linked"] = r.linked
            data.append(payload)
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
                linked_constraints=[
                    LinkedConstraint(name=lc["name"], expression=lc["expression"])
                    for lc in d.get("linked_constraints", [])
                ],
            )
            for d in data
        ]
        return cls(reqs)
