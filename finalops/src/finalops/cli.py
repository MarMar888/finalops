from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .graph import to_dot
from .ledger import DuplicateRequirementError, Ledger, RequirementKind
from .report import diagnose


def _load_ledger(path: str) -> Ledger:
    p = Path(path)
    if not p.exists():
        print(f"error: no ledger at '{path}' -- run `finalops ledger init {path}` first", file=sys.stderr)
        sys.exit(1)
    try:
        return Ledger.from_json(p)
    except json.JSONDecodeError as exc:
        print(f"error: '{path}' is not valid JSON ({exc})", file=sys.stderr)
        sys.exit(1)
    except (KeyError, ValueError) as exc:
        print(f"error: '{path}' doesn't look like a finalops ledger ({exc})", file=sys.stderr)
        sys.exit(1)


def _load_report(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        print(f"error: no report at '{path}' -- run finalops.run(model, out='{path}') first", file=sys.stderr)
        sys.exit(1)
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError as exc:
        print(f"error: '{path}' is not valid JSON ({exc})", file=sys.stderr)
        sys.exit(1)


def _cmd_ledger_init(args: argparse.Namespace) -> None:
    if Path(args.path).exists() and not args.force:
        print(f"{args.path} already exists (use --force to overwrite)", file=sys.stderr)
        sys.exit(1)
    Ledger().to_json(args.path)
    print(f"created empty ledger at {args.path}")


def _cmd_ledger_add(args: argparse.Namespace) -> None:
    path = Path(args.path)
    ledger = _load_ledger(args.path) if path.exists() else Ledger()
    try:
        ledger.add(id=args.id, description=args.description, source=args.source, kind=args.kind, units=args.units)
    except DuplicateRequirementError:
        print(f"error: requirement '{args.id}' already exists in '{path}' -- pick a different --id", file=sys.stderr)
        sys.exit(1)
    ledger.to_json(path)
    print(f"added requirement '{args.id}' to {path}")


def _cmd_ledger_list(args: argparse.Namespace) -> None:
    ledger = _load_ledger(args.path)
    if len(ledger) == 0:
        print("(empty ledger)")
        return
    for req in ledger:
        flag = "linked  " if req.linked else "UNLINKED"
        units = f" [units: {req.units}]" if req.units else ""
        print(f"[{flag}] {req.id} ({req.kind.value}): {req.description}  <- {req.source}{units}")
        for lc in req.linked_constraints:
            print(f"           -> {lc.name}: {lc.expression}")


def _cmd_ledger_graph(args: argparse.Namespace) -> None:
    ledger = _load_ledger(args.path)
    dot = to_dot(ledger)
    if args.out:
        Path(args.out).write_text(dot + "\n")
        print(f"wrote {args.out}")
    else:
        print(dot)


def _cmd_check(args: argparse.Namespace) -> None:
    report = _load_report(args.report)
    problems = diagnose(report, max_gap=args.max_gap)

    if problems:
        print("FAIL")
        for problem in problems:
            print(f"  - {problem}")
        sys.exit(1)

    print("PASS")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="finalops")
    sub = parser.add_subparsers(dest="command", required=True)

    ledger_parser = sub.add_parser("ledger", help="manage the requirement ledger")
    ledger_sub = ledger_parser.add_subparsers(dest="ledger_command", required=True)

    p_init = ledger_sub.add_parser("init", help="create an empty ledger file")
    p_init.add_argument("path", nargs="?", default="ledger.json", help="default: ledger.json")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=_cmd_ledger_init)

    p_add = ledger_sub.add_parser("add", help="register a requirement extracted from the brief")
    p_add.add_argument("path", nargs="?", default="ledger.json", help="default: ledger.json")
    p_add.add_argument("--id", required=True)
    p_add.add_argument("--description", required=True)
    p_add.add_argument("--source", required=True, help="where this rule came from, e.g. 'instructions.md:12'")
    p_add.add_argument("--kind", default="constraint", choices=[k.value for k in RequirementKind])
    p_add.add_argument("--units", default=None, help="e.g. 'hours/week' -- most relevant for decision_variable/data")
    p_add.set_defaults(func=_cmd_ledger_add)

    p_list = ledger_sub.add_parser("list", help="show requirements and their link status")
    p_list.add_argument("path", nargs="?", default="ledger.json", help="default: ledger.json")
    p_list.set_defaults(func=_cmd_ledger_list)

    p_graph = ledger_sub.add_parser(
        "graph",
        help="render the ledger as a Graphviz DOT graph (decision variables -> objective/constraints that reference them)",
    )
    p_graph.add_argument("path", nargs="?", default="ledger.json", help="default: ledger.json")
    p_graph.add_argument("--out", default=None, help="write DOT to this file instead of stdout")
    p_graph.set_defaults(func=_cmd_ledger_graph)

    p_check = sub.add_parser(
        "check",
        help="gate on a report.json produced by finalops.run() or finalops.report.build_report",
    )
    p_check.add_argument("report")
    p_check.add_argument("--max-gap", type=float, default=0.05)
    p_check.set_defaults(func=_cmd_check)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
