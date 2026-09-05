import json

import pytest

from finalops.cli import main


def test_ledger_init_and_add_and_list(tmp_path, capsys):
    path = tmp_path / "ledger.json"
    main(["ledger", "init", str(path)])
    main(
        [
            "ledger",
            "add",
            str(path),
            "--id",
            "demand",
            "--description",
            "meet demand",
            "--source",
            "brief.md:3",
        ]
    )
    capsys.readouterr()
    main(["ledger", "list", str(path)])
    out = capsys.readouterr().out
    assert "demand" in out
    assert "UNLINKED" in out


def test_ledger_init_refuses_overwrite_without_force(tmp_path):
    path = tmp_path / "ledger.json"
    main(["ledger", "init", str(path)])
    with pytest.raises(SystemExit) as exc:
        main(["ledger", "init", str(path)])
    assert exc.value.code == 1


def test_check_passes_on_clean_report(tmp_path, capsys):
    report = {
        "feasible": True,
        "violations": [],
        "unlinked_requirements": [],
        "quality_gap": 0.01,
    }
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))

    main(["check", str(path)])
    out = capsys.readouterr().out
    assert "PASS" in out


def test_check_fails_on_infeasible_report(tmp_path, capsys):
    report = {
        "feasible": False,
        "violations": [{"name": "demand", "slack": -5.0}],
        "unlinked_requirements": ["capacity"],
        "quality_gap": 0.5,
    }
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))

    with pytest.raises(SystemExit) as exc:
        main(["check", str(path), "--max-gap", "0.05"])
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "infeasible" in out
    assert "capacity" in out
    assert "quality gap" in out
