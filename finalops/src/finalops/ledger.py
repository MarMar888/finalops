from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path


class RequirementKind(str, Enum):
    CONSTRAINT = "constraint"
    OBJECTIVE = "objective"
    RESOURCE = "resource"


@dataclass
class Requirement:
    id: str
    description: str
    source: str
    kind: RequirementKind = RequirementKind.CONSTRAINT
    linked: bool = False


class DuplicateRequirementError(ValueError):
    pass


class Ledger:
    """The checklist-first artifact: every operational rule pulled from the brief
    gets registered here, with where it came from, before any model code is written.
    Constraints wired up later must cite a requirement id, so a rule that never
    makes it into the model shows up as an unlinked entry instead of silently
    disappearing.
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

    def mark_linked(self, id: str) -> None:
        if id not in self._by_id:
            raise KeyError(
                f"requirement '{id}' is not in the ledger — add it with ledger.add(...) "
                "before wiring it into a constraint"
            )
        self._by_id[id].linked = True

    def unlinked(self) -> list[Requirement]:
        return [r for r in self._by_id.values() if not r.linked]

    def to_json(self, path: str | Path) -> None:
        data = [{**asdict(r), "kind": r.kind.value} for r in self._by_id.values()]
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
                linked=d.get("linked", False),
            )
            for d in data
        ]
        return cls(reqs)
