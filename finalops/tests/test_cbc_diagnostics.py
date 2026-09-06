import pulp

from finalops import Ledger, Model, run, solve_with_diagnostics
from finalops.cbc_diagnostics import _parse_cbc_log

# Real CBC log excerpts (captured from an actual run) used to unit-test the
# parser without depending on timing to reproduce a "stopped early" solve.
TIMED_OUT_LOG = """
Cbc0020I Exiting on maximum time
Cbc0005I Partial search - best objective -1188 (best possible -1189.4668), took 7 iterations and 0 nodes (10.05 seconds)

Result - Stopped on time limit

Objective value:                1188.00000000
Upper bound:                    1189.467
Gap:                            -0.00
Enumerated nodes:               0
"""

PROVEN_OPTIMAL_LOG = """
Cbc0001I Search completed - best objective -222, took 0 iterations and 0 nodes (0.02 seconds)

Result - Optimal solution found

Objective value:                222.00000000
Enumerated nodes:               0
"""

PRESOLVED_LOG = """
Presolve 0 (-1) rows, 0 (-1) columns and 0 (-1) elements
Empty problem - 0 rows, 0 columns and 0 elements
Optimal - objective value 5
After Postsolve, objective 5, infeasibilities - dual 0 (0), primal 0 (0)
Optimal objective 5 - 0 iterations time 0.002, Presolve 0.00
"""


def test_parse_cbc_log_timed_out_is_not_proven_and_recovers_real_bound():
    diag = _parse_cbc_log(TIMED_OUT_LOG, status="Optimal", objective=1188.0)
    assert diag.proven_optimal is False
    assert diag.bound == 1189.467
    assert "time limit" in diag.result_line.lower()


def test_parse_cbc_log_proven_optimal():
    diag = _parse_cbc_log(PROVEN_OPTIMAL_LOG, status="Optimal", objective=222.0)
    assert diag.proven_optimal is True
    assert diag.bound == 222.0


def test_parse_cbc_log_presolved_with_no_result_line_still_counts_as_proven():
    # Small problems get solved by presolve alone with no "Result -" line at all.
    diag = _parse_cbc_log(PRESOLVED_LOG, status="Optimal", objective=5.0)
    assert diag.result_line is None
    assert diag.proven_optimal is True
    assert diag.bound == 5.0


def test_parse_cbc_log_infeasible_has_no_bound():
    diag = _parse_cbc_log("Result - Problem proven infeasible\n", status="Infeasible", objective=None)
    assert diag.proven_optimal is False
    assert diag.bound is None


def test_solve_with_diagnostics_real_solve_is_proven_optimal():
    ledger = Ledger()
    ledger.add(id="cost", description="minimize cost", source="brief:1", kind="objective")
    ledger.add(id="demand", description="meet demand", source="brief:2")

    model = Model("m", ledger)
    x = pulp.LpVariable("x", lowBound=0)
    model.set_objective(3 * x, requirement_id="cost")
    model.add_constraint(x >= 100, requirement_id="demand")

    result, diagnostics = solve_with_diagnostics(model)
    assert result.status == "Optimal"
    assert diagnostics.proven_optimal is True
    assert diagnostics.bound == result.objective


def test_run_uses_real_bound_not_lp_relaxation(tmp_path):
    ledger = Ledger()
    ledger.add(id="value", description="maximize value", source="brief:1", kind="objective")
    ledger.add(id="capacity", description="respect capacity", source="brief:2")

    model = Model("knapsack", ledger, sense=pulp.LpMaximize)
    items = [(5, 10), (4, 8), (3, 5)]  # (weight, value)
    xs = [pulp.LpVariable(f"x{i}", cat="Binary") for i in range(len(items))]

    model.set_objective(pulp.lpSum(v * xs[i] for i, (w, v) in enumerate(items)), requirement_id="value")
    model.add_constraint(
        pulp.lpSum(w * xs[i] for i, (w, v) in enumerate(items)) <= 7,
        requirement_id="capacity",
    )

    outcome = run(model, out=str(tmp_path / "report.json"))
    assert outcome.report["proven_optimal"] is True
    assert outcome.report["bound"] == outcome.report["objective"]
    assert outcome.report["quality_gap"] == 0.0
    assert outcome.passed is True
