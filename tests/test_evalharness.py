"""feat-073:确定性离线评测框架(evalharness)。

契约:全部内置用例离线全绿;用例崩溃记失败 check 不炸运行器;
未知用例 fail-closed 抛错;CLI `psyclaw eval` 落报告且退出码如实。
"""

from __future__ import annotations

import json
from pathlib import Path

from psyclaw.evalharness import CASES, format_report, run_evals


class TestRunEvals:
    def test_all_builtin_cases_green(self):
        """核心契约:内置评测全绿——编排/门禁/自学习链路端到端仍守约。"""
        report = run_evals()
        failed = [c["name"] for case in report["cases"].values()
                  for c in case["checks"] if not c["passed"]]
        assert report["all_passed"], f"评测失败项:{failed}"
        assert set(report["cases"]) == set(CASES)
        assert report["passed"] == report["total"] > 0
        assert report["failed"] == 0

    def test_subset_selection(self):
        report = run_evals(["lit_screen"])
        assert list(report["cases"]) == ["lit_screen"]
        assert report["total"] == report["cases"]["lit_screen"]["total"]

    def test_unknown_case_fail_closed(self):
        import pytest
        with pytest.raises(ValueError, match="未知评测用例"):
            run_evals(["no_such_case"])

    def test_case_crash_recorded_as_failure(self, monkeypatch):
        """用例自身崩溃 → 失败 check(fail-closed),运行器不炸、不静默跳过。"""
        def boom(tmp):
            raise RuntimeError("用例内部炸了")
        monkeypatch.setitem(CASES, "analysis_pipeline", (boom, "炸的用例"))
        report = run_evals(["analysis_pipeline"])
        assert not report["all_passed"]
        chk = report["cases"]["analysis_pipeline"]["checks"][0]
        assert not chk["passed"] and "崩溃" in chk["name"]
        assert "用例内部炸了" in chk["detail"]

    def test_report_structure_json_serializable(self):
        report = run_evals(["error_learning"])
        # 报告要能原样落盘(.psyclaw/eval_report.json)
        text = json.dumps(report, ensure_ascii=False)
        assert "error_learning" in text


class TestFormatReport:
    def test_all_passed_summary(self):
        report = run_evals(["gates_enforcement"])
        out = format_report(report)
        assert "gates_enforcement" in out and "✅" in out
        assert f"合计 {report['passed']}/{report['total']} 项通过" in out

    def test_failures_listed_with_detail(self):
        report = {"cases": {"fake": {"description": "假用例", "passed": 0, "total": 1,
                                     "checks": [{"name": "坏检查", "passed": False,
                                                 "detail": "细节X"}]}},
                  "total": 1, "passed": 0, "failed": 1, "all_passed": False}
        out = format_report(report)
        assert "❌" in out and "✗ 坏检查:细节X" in out and "1 项失败" in out


class TestCliEval:
    def test_cli_eval_writes_report_and_exits_zero(self, tmp_path, monkeypatch, capsys):
        from psyclaw import cli
        monkeypatch.chdir(tmp_path)
        rc = cli.main(["eval", "--case", "lit_screen"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "lit_screen" in out
        saved = json.loads(Path(".psyclaw/eval_report.json").read_text(encoding="utf-8"))
        assert saved["all_passed"] is True

    def test_cli_eval_json_output(self, tmp_path, monkeypatch, capsys):
        from psyclaw import cli
        monkeypatch.chdir(tmp_path)
        rc = cli.main(["eval", "--case", "error_learning", "--json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["all_passed"] is True

    def test_cli_eval_unknown_case_exit_one(self, tmp_path, monkeypatch, capsys):
        from psyclaw import cli
        monkeypatch.chdir(tmp_path)
        rc = cli.main(["eval", "--case", "nope"])
        assert rc == 1
        assert "未知评测用例" in capsys.readouterr().out
