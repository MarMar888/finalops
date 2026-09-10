from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .infeasibility import InfeasibilityDiagnosis
from .solve import SolveResult
from .validate import check_feasibility, quality_gap


def build_report(
    model,
    result: SolveResult,
    out: str | Path | None = None,
    bound: float | None = None,
    proven_optimal: bool | None = None,
    infeasibility: InfeasibilityDiagnosis | None = None,
) -> dict:
    """Combine ledger coverage, feasibility, and quality-gap into one artifact an
    agent (or `finalops check`) can gate on, instead of stopping at 'it ran'.

    Pass `bound`/`proven_optimal` (from `cbc_diagnostics.solve_with_diagnostics`)
    for an honest, solver-reported quality gap instead of the LP-relaxation
    fallback. Pass `infeasibility` (from `infeasibility.explain_infeasibility`)
    when the solver reported the model infeasible, so the report explains
    *why*, tied back to ledger requirements, instead of just `feasible: false`.
    """
    unlinked = [r.id for r in model.ledger.unlinked()]

    if infeasibility is not None:
        feasible = infeasibility.feasible
        violations = [asdict(v) for v in infeasibility.violations]
        gap = None
    else:
        feasibility_report = check_feasibility(model)
        feasible = feasibility_report.feasible
        violations = [asdict(v) for v in feasibility_report.violations]
        gap = quality_gap(model, result.objective, bound=bound)

    report = {
        "model": model.name,
        "status": result.status,
        "objective": result.objective,
        "proven_optimal": proven_optimal,
        "bound": bound,
        "feasible": feasible,
        "violations": violations,
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
        violations = report.get("violations", [])
        if violations and "requirement_id" in violations[0]:
            for v in violations:
                label = v.get("requirement_id") or v.get("constraint_name")
                problems.append(f"infeasible: requirement '{label}' violated by {v['magnitude']:.4g}")
        else:
            problems.append(f"infeasible: {len(violations)} constraint(s) violated")

    unlinked = report.get("unlinked_requirements", [])
    if unlinked:
        problems.append(f"{len(unlinked)} ledger requirement(s) never linked to a constraint: {', '.join(unlinked)}")

    gap = report.get("quality_gap")
    if gap is not None and gap > max_gap:
        problems.append(f"quality gap {gap:.2%} exceeds threshold {max_gap:.2%}")

    return problems
