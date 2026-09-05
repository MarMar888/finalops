from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pulp

from .report import build_report, diagnose
from .solve import solve

_SOLVERS = {
    "cbc": lambda time_limit: pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit),
}


@dataclass
class RunResult:
    passed: bool
    report: dict
    problems: list[str]


def run(
    model,
    *,
    solver: str = "cbc",
    time_limit: float | None = None,
    max_gap: float = 0.05,
    out: str | Path | None = "report.json",
) -> RunResult:
    """The one call an agent should make once its model is built and every
    constraint/objective is tagged against the ledger: solve it, check
    feasibility, check ledger coverage, check the quality gap, and hand back
    a single verdict — instead of chaining solve() -> build_report() -> check
    as three separate steps an agent could stop short of.

    `model` is a `finalops.Model` (the ledger-aware wrapper), not a raw
    `pulp.LpProblem` — ledger coverage can't be checked without it. Reach
    into `model.problem` if you need the underlying PuLP object directly.
    """
    if solver not in _SOLVERS:
        raise ValueError(f"unknown solver '{solver}', available: {sorted(_SOLVERS)}")

    backend = _SOLVERS[solver](time_limit)
    result = solve(model, solver=backend)
    report = build_report(model, result, out=out)
    problems = diagnose(report, max_gap=max_gap)

    return RunResult(passed=not problems, report=report, problems=problems)
