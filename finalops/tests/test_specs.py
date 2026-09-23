import json

import pulp
import pytest
from pydantic import ValidationError

from finalops import (
    CapacityLimit,
    CustomConstraint,
    DemandCoverage,
    DuplicateRequirementError,
    Ledger,
    Model,
    RuleViolation,
    Spec,
    UnknownDataError,
    UnknownVariableError,
    build_debug_bundle,
    run,
)


def _plan() -> Ledger:
    ledger = Ledger()
    ledger.variable("widgets", units="units/week", source="brief:2")
    ledger.variable("gadgets", units="units/week", source="brief:2")
    ledger.data("widget_cost", 3, units="$/unit", source="brief:1")
    ledger.data("gadget_cost", 5, units="$/unit", source="brief:1")
    ledger.minimize("cost", {"widgets": "widget_cost", "gadgets": "gadget_cost"}, source="brief:1")
    ledger.constrain(DemandCoverage(id="demand", required=100, covered_by=["widgets", "gadgets"], source="brief:3"))
    ledger.constrain(CapacityLimit(id="capacity", limit=240, uses={"widgets": 1, "gadgets": 2}, source="brief:5"))
    return ledger


def test_ledger_only_model_builds_solves_and_links_everything():
    ledger = _plan()
    outcome = run(ledger, out=None)

    assert outcome.passed is True
    assert outcome.report["objective"] == pytest.approx(300.0)
    assert outcome.report["rule_violations"] == []
    assert ledger.unlinked() == []
    assert outcome.model is not None and outcome.model.ledger is ledger


def test_data_is_resolved_by_id_and_records_where_it_was_used():
    ledger = _plan()
    run(ledger, out=None)
    (link,) = ledger.get("widget_cost").linked_constraints
    assert link.expression == "3 $/unit (used by cost)"


def test_data_nothing_uses_is_flagged():
    ledger = _plan()
    ledger.data("overtime_rate", 9, units="$/hour", source="brief:7")
    outcome = run(ledger, out=None)
    assert outcome.passed is False
    assert any("overtime_rate" in p for p in outcome.problems)


def test_rebuilding_from_the_same_ledger_does_not_duplicate_links():
    ledger = _plan()
    Model.from_ledger(ledger)
    Model.from_ledger(ledger)
    assert len(ledger.get("demand").linked_constraints) == 1
    assert len(ledger.get("widget_cost").linked_constraints) == 1


def test_maximize_sets_the_sense():
    ledger = Ledger()
    ledger.variable("x", source="b:1")
    ledger.maximize("profit", {"x": 2}, source="b:1")
    ledger.constrain(CapacityLimit(id="cap", limit=10, uses={"x": 1}, source="b:2"))
    outcome = run(ledger, out=None)
    assert outcome.report["objective"] == pytest.approx(20.0)


def test_only_one_objective_allowed():
    ledger = _plan()
    ledger.maximize("profit", {"widgets": 1}, source="brief:9")
    with pytest.raises(ValueError, match="one objective"):
        Model.from_ledger(ledger)


# -- catching mistakes early ------------------------------------------------------


def test_a_typo_in_a_variable_name_fails_and_lists_the_real_ones():
    ledger = _plan()
    ledger.constrain(CapacityLimit(id="oops", limit=5, uses={"widgts": 1}, source="brief:8"))
    with pytest.raises(UnknownVariableError, match="widgts.*gadgets, widgets"):
        Model.from_ledger(ledger)


def test_a_reference_to_missing_data_fails_and_lists_the_real_ids():
    ledger = Ledger()
    ledger.variable("x", source="b:1")
    ledger.minimize("cost", {"x": "unit_cost"}, source="b:1")
    with pytest.raises(UnknownDataError, match="unit_cost"):
        Model.from_ledger(ledger)


def test_unknown_parameter_names_are_rejected():
    with pytest.raises(ValidationError):
        CapacityLimit(id="c", source="s", limt=5, uses={"x": 1})  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "build",
    [
        lambda: CapacityLimit(id="c", source="s", limit=5, uses={}),
        lambda: CapacityLimit(id="c", source="s", limit=float("inf"), uses={"x": 1}),
        lambda: CapacityLimit(id="c", source="", limit=5, uses={"x": 1}),
        lambda: Ledger().variable("not-a-name", source="s"),
    ],
)
def test_invalid_specs_are_rejected(build):
    with pytest.raises(ValidationError):
        build()


def test_a_rule_registered_from_the_brief_gets_defined_later():
    ledger = Ledger()
    ledger.add(id="demand", description="meet weekly demand", source="brief:3")
    ledger.variable("x", source="b:2")
    ledger.minimize("cost", {"x": 1}, source="b:1")

    assert [r.id for r in ledger.unlinked()] == ["demand", "x", "cost"]
    ledger.constrain(DemandCoverage(id="demand", required=5, covered_by=["x"], source="brief:3"))
    Model.from_ledger(ledger)
    assert ledger.unlinked() == []
    assert ledger.get("demand").description == "meet weekly demand"


def test_a_requirement_never_defined_stays_unlinked_and_is_flagged():
    ledger = _plan()
    ledger.add(id="safety_stock", description="keep 20 units back", source="brief:footnote")
    outcome = run(ledger, out=None)
    assert outcome.passed is False
    assert any("safety_stock" in p for p in outcome.problems)


def test_defining_a_requirement_as_the_wrong_kind_or_twice_is_an_error():
    ledger = _plan()
    with pytest.raises(ValueError, match="registered as data"):
        ledger.constrain(CapacityLimit(id="widget_cost", limit=1, uses={"widgets": 1}, source="s"))
    with pytest.raises(DuplicateRequirementError):
        ledger.constrain(CapacityLimit(id="capacity", limit=1, uses={"widgets": 1}, source="s"))


# -- the independent check --------------------------------------------------------


class SloppyCapacity(CapacityLimit):
    """A rule whose algebra is wrong (allows 10 more than the limit), as a buggy
    hand-written encoding would be. The solver happily satisfies the wrong constraint."""

    def compile(self, model):
        used = pulp.lpSum(model.quantity(c) * model.var(v) for v, c in self.uses.items())
        return [used <= model.quantity(self.limit) + 10]


def test_check_catches_algebra_that_does_not_say_what_the_rule_says():
    ledger = Ledger()
    ledger.variable("widgets", units="units", source="b:1")
    ledger.maximize("profit", {"widgets": 1}, source="b:1")
    ledger.constrain(SloppyCapacity(id="cap", limit=100, uses={"widgets": 1}, source="b:2", units="units"))

    outcome = run(ledger, out=None)

    assert outcome.report["objective"] == pytest.approx(110.0)  # the solver believed the bad algebra
    assert outcome.passed is False
    assert any(p.startswith("rule 'cap' violated") and "110" in p for p in outcome.problems)


def test_check_reports_a_variable_with_no_solved_value():
    model = Model.from_ledger(_plan())
    rule = CapacityLimit(id="c", limit=5, uses={"widgets": 1}, source="s")
    (violation,) = rule.check(model, {})
    assert isinstance(violation, RuleViolation) and "no solved value" in violation.message


def test_check_reports_how_far_a_solution_is_off():
    model = Model.from_ledger(_plan())
    violations = model.check_rules({"widgets": 30, "gadgets": 20})  # demand 50 < 100
    assert [(v.rule_id, v.amount) for v in violations] == [("demand", 50)]


# -- escape hatch -----------------------------------------------------------------


def test_custom_constraint_builds_from_the_model_and_is_enforced():
    ledger = _plan()
    ledger.constrain(
        CustomConstraint(
            id="mix",
            source="brief:9",
            description="at least as many gadgets as widgets",
            build=lambda m: m.var("gadgets") >= m.var("widgets"),
        )
    )
    outcome = run(ledger, out=None)
    values = outcome.model.problem.variablesDict()
    assert values["gadgets"].value() >= values["widgets"].value() - 1e-9


def test_custom_constraint_can_bring_its_own_check():
    ledger = _plan()
    ledger.constrain(
        CustomConstraint(
            id="mix",
            source="brief:9",
            build=lambda m: m.var("gadgets") >= 0,  # deliberately does not enforce the rule
            check_fn=lambda m, v: [RuleViolation("mix", "expected more gadgets than widgets")] if v["gadgets"] < v["widgets"] else [],
        )
    )
    outcome = run(ledger, out=None)
    assert any("rule 'mix' violated" in p for p in outcome.problems)


def test_custom_constraint_must_build_a_real_constraint():
    ledger = _plan()
    ledger.constrain(CustomConstraint(id="bad", source="s", build=lambda m: 1 >= 0))
    with pytest.raises(TypeError, match="bool"):
        Model.from_ledger(ledger)


# -- model-first use --------------------------------------------------------------


def test_model_add_registers_the_rule_in_the_ledger_and_links_it():
    ledger = Ledger()
    model = Model("m", ledger)
    ledger.add(id="x_qty", description="x", source="b:1", kind="decision_variable")
    model.add_variable(pulp.LpVariable("x", lowBound=0), requirement_id="x_qty")

    model.add(DemandCoverage(id="need", required=4, covered_by=["x"], source="brief:3", description="produce 4", units="units"))

    req = ledger.get("need")
    assert (req.description, req.source, req.units) == ("produce 4", "brief:3", "units")
    assert req.linked_constraints[0].name == "need"
    with pytest.raises(ValueError, match="already added"):
        model.add(DemandCoverage(id="need", required=4, covered_by=["x"], source="brief:3"))


# -- persistence ------------------------------------------------------------------


def test_the_ledger_round_trips_through_json_and_still_builds_the_same_model(tmp_path):
    path = tmp_path / "ledger.json"
    _plan().to_json(path)

    saved = json.loads(path.read_text())
    assert {r["id"]: r["spec"]["type"] for r in saved}["capacity"] == "CapacityLimit"

    reloaded = Ledger.from_json(path)
    outcome = run(reloaded, out=None)
    assert outcome.passed is True
    assert outcome.report["objective"] == pytest.approx(300.0)


def test_a_custom_constraint_cannot_be_saved(tmp_path):
    ledger = _plan()
    ledger.constrain(CustomConstraint(id="mix", source="s", build=lambda m: m.var("gadgets") >= 0))
    with pytest.raises(TypeError, match="CustomConstraint"):
        ledger.to_json(tmp_path / "ledger.json")


def test_unknown_spec_type_in_a_file_says_what_is_known():
    with pytest.raises(ValueError, match="unknown spec type.*CapacityLimit"):
        Spec.from_dict({"type": "Nonsense", "id": "x", "source": "s"})


def test_debug_bundle_accepts_a_ledger():
    bundle = build_debug_bundle(_plan(), name="plan")
    assert bundle["model"] == "plan"
    assert bundle["summary"]["status"] == "Optimal"
    assert {c["requirement_id"] for c in bundle["constraints"]} == {"demand", "capacity"}
