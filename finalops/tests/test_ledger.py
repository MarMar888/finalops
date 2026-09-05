import pytest

from finalops import DuplicateRequirementError, Ledger, RequirementKind


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
        ledger.mark_linked("nope")


def test_unlinked_tracks_only_unmarked():
    ledger = Ledger()
    ledger.add(id="a", description="a", source="s")
    ledger.add(id="b", description="b", source="s")
    ledger.mark_linked("a")
    unlinked = ledger.unlinked()
    assert [r.id for r in unlinked] == ["b"]


def test_roundtrip_json(tmp_path):
    ledger = Ledger()
    ledger.add(id="cost", description="minimize cost", source="brief.md:1", kind="objective")
    ledger.mark_linked("cost")
    path = tmp_path / "ledger.json"
    ledger.to_json(path)

    reloaded = Ledger.from_json(path)
    req = reloaded.get("cost")
    assert req.kind == RequirementKind.OBJECTIVE
    assert req.linked is True


def test_from_json_empty_file(tmp_path):
    path = tmp_path / "ledger.json"
    Ledger().to_json(path)
    reloaded = Ledger.from_json(path)
    assert len(reloaded) == 0
