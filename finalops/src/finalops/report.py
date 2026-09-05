from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .solve import SolveResult
from .validate import check_feasibility, quality_gap


def build_report(model, result: SolveResult, out: str | Path | None = None) -> dict:
    """Combine ledger coverage, feasibility, and quality-gap into one artifact an
    agent (or `finalops check`) can gate on, instead of stopping at 'it ran'.
    """
    feasibility = check_feasibility(model)
    gap = quality_gap(model, result.objective)
    unlinked = [r.id for r in model.ledger.unlinked()]

    report = {
        "model": model.name,
        "status": result.status,
        "objective": result.objective,
        "feasible": feasibility.feasible,
        "violations": [asdict(v) for v in feasibility.violations],
        "quality_gap": gap,
        "requirement_count": len(model.ledger),
        "unlinked_requirements": unlinked,
    }

    if out:
        Path(out).write_text(json.dumps(report, indent=2) + "\n")

    return report


def diagnose(report: dict, max_gap: float = 0.05) -> list[str]:
    """Turn a report dict into a list of human-readable problems. Empty means pass.
    Shared by `finalops.run()` and `finalops check` so the two never drift apart.
    """
    problems = []

    if not report.get("feasible", False):
        problems.append(f"infeasible: {len(report.get('violations', []))} constraint(s) violated")

    unlinked = report.get("unlinked_requirements", [])
    if unlinked:
        problems.append(f"{len(unlinked)} ledger requirement(s) never linked to a constraint: {', '.join(unlinked)}")

    gap = report.get("quality_gap")
    if gap is not None and gap > max_gap:
        problems.append(f"quality gap {gap:.2%} exceeds threshold {max_gap:.2%}")

    return problems
