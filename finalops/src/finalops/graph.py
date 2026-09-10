from __future__ import annotations

import re

from .ledger import Ledger, RequirementKind

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

_SHAPE_BY_KIND = {
    RequirementKind.DECISION_VARIABLE: "box",
    RequirementKind.OBJECTIVE: "diamond",
    RequirementKind.CONSTRAINT: "ellipse",
    RequirementKind.DATA: "note",
}

_COLOR_BY_KIND = {
    RequirementKind.DECISION_VARIABLE: "lightblue",
    RequirementKind.OBJECTIVE: "gold",
    RequirementKind.CONSTRAINT: "lightgreen",
    RequirementKind.DATA: "lightgrey",
}


def _escape(text: str) -> str:
    return text.replace('"', '\\"')


def to_dot(ledger: Ledger) -> str:
    """Render the ledger as a Graphviz DOT graph: one node per requirement,
    shaped and colored by kind, with an edge from each decision variable to
    every objective/constraint whose linked expression actually references
    it (found by tokenizing the expression text PuLP recorded at link time --
    no live Model object needed, this works straight off the ledger JSON).
    Unlinked requirements are drawn dashed with a red border, so a gap is
    visible in the picture, not just in `ledger list` text output.
    """
    requirements = list(ledger)

    variable_names: dict[str, str] = {
        req.linked_constraints[0].name: req.id
        for req in requirements
        if req.kind == RequirementKind.DECISION_VARIABLE and req.linked_constraints
    }

    lines = [
        "digraph finalops_ledger {",
        '  rankdir="LR";',
        "  node [style=filled, fontname=Helvetica];",
    ]

    for req in requirements:
        shape = _SHAPE_BY_KIND[req.kind]
        color = _COLOR_BY_KIND[req.kind] if req.linked else "white"
        style_extra = ', color="red", style="filled,dashed"' if not req.linked else ""
        label = f"{req.id}\\n({req.kind.value})"
        if req.units:
            label += f"\\n[{req.units}]"
        lines.append(f'  "{req.id}" [label="{_escape(label)}", shape={shape}, fillcolor="{color}"{style_extra}];')

    edges: set[tuple[str, str]] = set()
    for req in requirements:
        if req.kind == RequirementKind.DECISION_VARIABLE:
            continue
        for lc in req.linked_constraints:
            tokens = set(_TOKEN_RE.findall(lc.expression))
            for var_name, var_req_id in variable_names.items():
                if var_name in tokens:
                    edges.add((var_req_id, req.id))

    for src, dst in sorted(edges):
        lines.append(f'  "{src}" -> "{dst}";')

    lines.append("}")
    return "\n".join(lines)
