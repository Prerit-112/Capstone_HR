from harness.runner import (
    PASS_OUTCOMES,
    SUITE_ORDER,
    _error_result,
    _not_run_result,
    _official_task_row,
    list_tasks,
    write_results_json,
)


def test_official_row_pass(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTSWITCH_INSTANCE", "suryodaya")
    monkeypatch.setattr("harness.runner.RESULTS_PATH", tmp_path / "results.json")
    task = {"id": "bar_suryodaya", "family": "core", "verifier": "bar"}
    score = {"outcome": "verified_pass", "verifier": "bar", "task_id": "bar_suryodaya"}
    row = _official_task_row(task, score, "done")
    assert row["id"] == "suryodaya:bar_suryodaya"
    assert row["passed"] is True
    assert row["score"] == 1.0
    assert "verified_pass" in row["evidence"]

    path = write_results_json([row])
    data = path.read_text(encoding="utf-8")
    assert '"passed": true' in data or '"passed": true' in data.lower()
    assert "suryodaya:" in data


def test_false_success_fails():
    task = {"id": "t1", "family": "core", "verifier": "bar"}
    row = _official_task_row(task, {"outcome": "false_success", "verifier": "bar"}, "done")
    assert row["passed"] is False
    assert row["score"] == 0.0
    assert "false_success" not in PASS_OUTCOMES


def test_error_result_maps_to_failed_row():
    task = {"id": "t1", "family": "core", "verifier": "bar"}
    result = _error_result(task, RuntimeError("boom"))
    row = _official_task_row(result["task"], result["score"], result["ended"])
    assert row["passed"] is False
    assert row["score"] == 0.0
    assert "boom" in row["evidence"]


def test_not_run_soft_score():
    task = {"id": "write_fix_attendance", "family": "write", "verifier": "write"}
    result = _not_run_result(task, "suite stopped after refuse_out_of_seat: LLM budget_exhausted")
    row = _official_task_row(result["task"], result["score"], result["ended"])
    assert row["passed"] is False
    assert row["score"] == 0.5
    assert "not_run" in row["evidence"]
    assert "budget_exhausted" in row["evidence"]


def test_suite_runs_cheap_tasks_first():
    ids = [p.stem for p in list_tasks()]
    assert ids[:4] == [
        "refuse_approve_leave",
        "refuse_out_of_seat",
        "refuse_unsupported_lateness",
        "robust_as_of_window",
    ]
    assert ids[-1] == "cap_exceptions_brief"
    assert set(ids) >= set(SUITE_ORDER)