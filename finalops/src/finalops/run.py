from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .cbc_diagnostics import solve_with_diagnostics
from .infeasibility import explain_infeasibility
from .report import build_report, diagnose

_SOLVERS = {"cbc"}


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
    constraint/objective is tagged against the ledger: solve it, and get back
    a single verdict instead of chaining solve -> report -> check as three
    separate steps an agent could stop short of.

    Two things this does beyond a bare solve:
    - If the solver proves infeasibility, it doesn't just report the word
      "infeasible" — it relaxes every constraint, resolves, and reports which
      ledger requirements are responsible and by how much.
    - The quality gap is computed against the solver's own internally-tracked
      bound (recovered from the CBC log), not a looser LP-relaxation guess.

    `model` is a `finalops.Model` (the ledger-aware wrapper), not a raw
    `pulp.LpProblem` — ledger coverage can't be checked without it. Reach
    into `model.problem` if you need the underlying PuLP object directly.
    """
    if solver not in _SOLVERS:
        raise ValueError(f"unknown solver '{solver}', available: {sorted(_SOLVERS)}")

    result, diagnostics = solve_with_diagnostics(model, time_limit=time_limit)

    infeasibility = explain_infeasibility(model) if result.status == "Infeasible" else None

    report = build_report(
        model,
        result,
        out=out,
        bound=diagnostics.bound,
        proven_optimal=diagnostics.proven_optimal,
        infeasibility=infeasibility,
    )
    problems = diagnose(report, max_gap=max_gap)

    return RunResult(passed=not problems, report=report, problems=problems)
