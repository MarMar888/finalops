from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pulp

from .solve import SolveResult

_RESULT_RE = re.compile(r"^Result -\s*(.+)$", re.MULTILINE)
_BOUND_RE = re.compile(r"^(?:Lower|Upper) bound:\s*([-\d.eE]+)", re.MULTILINE)


@dataclass
class CbcDiagnostics:
    result_line: str | None
    proven_optimal: bool
    bound: float | None
    raw_log: str


def _parse_cbc_log(text: str, status: str, objective: float | None) -> CbcDiagnostics:
    result_match = _RESULT_RE.search(text)
    result_line = result_match.group(1).strip() if result_match else None

    if status != "Optimal":
        # Infeasible/Unbounded/Undefined: no incumbent-relative bound to report here.
        return CbcDiagnostics(result_line=result_line, proven_optimal=False, bound=None, raw_log=text)

    if result_line is None or "optimal solution found" in result_line.lower():
        # Either CBC's own "proven optimal" message, or the problem was small
        # enough that presolve solved it before any "Result -" line was ever
        # printed. Either way it's proven, so the bound is exactly the objective.
        return CbcDiagnostics(result_line=result_line, proven_optimal=True, bound=objective, raw_log=text)

    # PuLP reports LpStatus "Optimal" for a partial search too (it just means
    # "a feasible incumbent exists"), so the log's own Result line is the only
    # honest way to tell "proven" from "timed out with a decent answer" apart.
    bound_match = _BOUND_RE.search(text)
    bound = float(bound_match.group(1)) if bound_match else None
    return CbcDiagnostics(result_line=result_line, proven_optimal=False, bound=bound, raw_log=text)


def solve_with_diagnostics(model, time_limit: float | None = None) -> tuple[SolveResult, CbcDiagnostics]:
    """Solve with CBC and recover the bound and termination reason CBC already
    computes internally during branch-and-bound but that PuLP's LpStatus/
    objective pair normally discards, instead of approximating a bound via
    LP relaxation.
    """
    fd, log_path = tempfile.mkstemp(suffix=".cbc.log")
    os.close(fd)
    try:
        solver = pulp.PULP_CBC_CMD(msg=False, logPath=log_path, timeLimit=time_limit)
        model.problem.solve(solver)
        status = pulp.LpStatus[model.problem.status]
        objective = pulp.value(model.problem.objective)
        variables = {v.name: v.varValue for v in model.problem.variables()}
        result = SolveResult(status=status, objective=objective, variables=variables)

        log_text = Path(log_path).read_text()
        diagnostics = _parse_cbc_log(log_text, status, objective)
        return result, diagnostics
    finally:
        os.unlink(log_path)
