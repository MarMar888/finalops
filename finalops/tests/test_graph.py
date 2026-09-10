import pulp

from finalops import Ledger, Model, to_dot


def _linked_ledger():
    ledger = Ledger()
    ledger.add(id="x_qty", description="x per week", source="brief:1", kind="decision_variable", units="units/week")
    ledger.add(id="cost", description="minimize cost", source="brief:2", kind="objective")
    ledger.add(id="demand", description="meet demand", source="brief:3")
    ledger.add(id="unit_cost", description="cost per unit", source="brief:2", kind="data", units="$/unit")
    ledger.add(id="unused", description="never wired up", source="brief:4")

    model = Model("m", ledger)
    x = model.add_variable(pulp.LpVariable("x", lowBound=0), requirement_id="x_qty", units="units/week")
    model.cite_data("unit_cost", note="3.0 $/unit, from brief:2")
    model.set_objective(3 * x, requirement_id="cost")
    model.add_constraint(x >= 100, requirement_id="demand")
    return ledger


def test_to_dot_includes_a_node_per_requirement():
    dot = to_dot(_linked_ledger())
    for req_id in ["x_qty", "cost", "demand", "unit_cost", "unused"]:
        assert f'"{req_id}"' in dot


def test_to_dot_draws_edges_from_variable_to_referencing_requirements():
    dot = to_dot(_linked_ledger())
    assert '"x_qty" -> "cost";' in dot
    assert '"x_qty" -> "demand";' in dot
    # unit_cost's citation is a free-text note, not an expression referencing x.
    assert '"x_qty" -> "unit_cost";' not in dot


def test_to_dot_marks_unlinked_requirements_dashed_red():
    dot = to_dot(_linked_ledger())
    unused_line = next(line for line in dot.splitlines() if line.strip().startswith('"unused"'))
    assert "red" in unused_line
    assert "dashed" in unused_line


def test_to_dot_is_valid_digraph_syntax():
    dot = to_dot(_linked_ledger())
    assert dot.startswith("digraph finalops_ledger {")
    assert dot.rstrip().endswith("}")


def test_to_dot_on_empty_ledger():
    dot = to_dot(Ledger())
    assert dot.startswith("digraph finalops_ledger {")
    assert dot.rstrip().endswith("}")
