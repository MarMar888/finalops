from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .ledger import Ledger, RequirementKind
from .report import diagnose


def _cmd_ledger_init(args: argparse.Namespace) -> None:
    if Path(args.path).exists() and not args.force:
        print(f"{args.path} already exists (use --force to overwrite)", file=sys.stderr)
        sys.exit(1)
    Ledger().to_json(args.path)
    print(f"created empty ledger at {args.path}")


def _cmd_ledger_add(args: argparse.Namespace) -> None:
    path = Path(args.path)
    ledger = Ledger.from_json(path) if path.exists() else Ledger()
    ledger.add(id=args.id, description=args.description, source=args.source, kind=args.kind)
    ledger.to_json(path)
    print(f"added requirement '{args.id}' to {path}")


def _cmd_ledger_list(args: argparse.Namespace) -> None:
    ledger = Ledger.from_json(args.path)
    if len(ledger) == 0:
        print("(empty ledger)")
        return
    for req in ledger:
        flag = "linked  " if req.linked else "UNLINKED"
        print(f"[{flag}] {req.id} ({req.kind.value}): {req.description}  <- {req.source}")


def _cmd_check(args: argparse.Namespace) -> None:
    report = json.loads(Path(args.report).read_text())
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
    p_init.add_argument("path")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=_cmd_ledger_init)

    p_add = ledger_sub.add_parser("add", help="register a requirement extracted from the brief")
    p_add.add_argument("path")
    p_add.add_argument("--id", required=True)
    p_add.add_argument("--description", required=True)
    p_add.add_argument("--source", required=True, help="where this rule came from, e.g. 'instructions.md:12'")
    p_add.add_argument("--kind", default="constraint", choices=[k.value for k in RequirementKind])
    p_add.set_defaults(func=_cmd_ledger_add)

    p_list = ledger_sub.add_parser("list", help="show requirements and their link status")
    p_list.add_argument("path")
    p_list.set_defaults(func=_cmd_ledger_list)

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
