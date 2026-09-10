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


def test_ledger_commands_default_path_to_ledger_json(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    main(["ledger", "init"])
    assert (tmp_path / "ledger.json").exists()

    main(["ledger", "add", "--id", "demand", "--description", "meet demand", "--source", "brief.md:3"])
    capsys.readouterr()

    main(["ledger", "list"])
    out = capsys.readouterr().out
    assert "demand" in out

    main(["ledger", "graph"])
    dot = capsys.readouterr().out
    assert '"demand"' in dot


def test_ledger_list_on_missing_file_gives_clean_error(tmp_path, capsys):
    missing = tmp_path / "nope.json"
    with pytest.raises(SystemExit) as exc:
        main(["ledger", "list", str(missing)])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "no ledger" in err
    assert "ledger init" in err


def test_ledger_graph_on_missing_file_gives_clean_error(tmp_path, capsys):
    missing = tmp_path / "nope.json"
    with pytest.raises(SystemExit) as exc:
        main(["ledger", "graph", str(missing)])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "no ledger" in err


def test_ledger_list_on_invalid_json_gives_clean_error(tmp_path, capsys):
    path = tmp_path / "ledger.json"
    path.write_text("{not valid json")
    with pytest.raises(SystemExit) as exc:
        main(["ledger", "list", str(path)])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "not valid JSON" in err


def test_ledger_add_duplicate_id_gives_clean_error(tmp_path, capsys):
    path = tmp_path / "ledger.json"
    main(["ledger", "init", str(path)])
    main(["ledger", "add", str(path), "--id", "demand", "--description", "meet demand", "--source", "brief.md:3"])
    capsys.readouterr()

    with pytest.raises(SystemExit) as exc:
        main(["ledger", "add", str(path), "--id", "demand", "--description", "again", "--source", "brief.md:4"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "already exists" in err


def test_check_on_missing_file_gives_clean_error(tmp_path, capsys):
    missing = tmp_path / "nope.json"
    with pytest.raises(SystemExit) as exc:
        main(["check", str(missing)])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "no report" in err


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
