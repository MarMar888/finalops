import pytest

from finalops import DuplicateRequirementError, Ledger, RequirementKind
from finalops.ledger import LinkedConstraint


def test_add_and_get():
    ledger = Ledger()
    ledger.add(id="demand", description="meet demand", source="brief.md:3")
    req = ledger.get("demand")
    assert req.description == "meet demand"
    assert req.kind == RequirementKind.CONSTRAINT
    assert req.linked is False


def test_duplicate_id_rejected():
    ledger = Ledger()
    ledger.add(id="demand", description="meet demand", source="brief.md:3")
    with pytest.raises(DuplicateRequirementError):
        ledger.add(id="demand", description="again", source="brief.md:4")


def test_mark_linked_unknown_id_raises():
    ledger = Ledger()
    with pytest.raises(KeyError):
        ledger.mark_linked("nope", constraint_name="c1", expression="x >= 1")


def test_unlinked_tracks_only_unmarked():
    ledger = Ledger()
    ledger.add(id="a", description="a", source="s")
    ledger.add(id="b", description="b", source="s")
    ledger.mark_linked("a", constraint_name="c1", expression="x >= 1")
    unlinked = ledger.unlinked()
    assert [r.id for r in unlinked] == ["b"]


def test_mark_linked_records_constraint_details():
    ledger = Ledger()
    ledger.add(id="capacity", description="respect capacity", source="brief.md:5")
    ledger.mark_linked("capacity", constraint_name="c2", expression="x + 2*y <= 240")

    req = ledger.get("capacity")
    assert req.linked is True
    assert req.linked_constraints == [LinkedConstraint(name="c2", expression="x + 2*y <= 240")]


def test_mark_linked_supports_multiple_constraints_per_requirement():
    ledger = Ledger()
    ledger.add(id="shared", description="applies to both shifts", source="brief.md:9")
    ledger.mark_linked("shared", constraint_name="c1", expression="x <= 10")
    ledger.mark_linked("shared", constraint_name="c2", expression="y <= 10")

    req = ledger.get("shared")
    assert [lc.name for lc in req.linked_constraints] == ["c1", "c2"]


def test_roundtrip_json(tmp_path):
    ledger = Ledger()
    ledger.add(id="cost", description="minimize cost", source="brief.md:1", kind="objective")
    ledger.mark_linked("cost", constraint_name="objective", expression="3*x + 5*y")
    path = tmp_path / "ledger.json"
    ledger.to_json(path)

    reloaded = Ledger.from_json(path)
    req = reloaded.get("cost")
    assert req.kind == RequirementKind.OBJECTIVE
    assert req.linked is True
    assert req.linked_constraints == [LinkedConstraint(name="objective", expression="3*x + 5*y")]


def test_from_json_empty_file(tmp_path):
    path = tmp_path / "ledger.json"
    Ledger().to_json(path)
    reloaded = Ledger.from_json(path)
    assert len(reloaded) == 0
