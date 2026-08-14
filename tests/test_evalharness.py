"""feat-073:确定性离线评测框架(evalharness)。

契约:全部内置用例离线全绿;用例崩溃记失败 check 不炸运行器;
未知用例 fail-closed 抛错;CLI `psyclaw eval` 落报告且退出码如实。
"""

from __future__ import annotations

import json
from pathlib import Path

from psyclaw.evalharness import CASES, format_report, run_evals, validate_agent_case_spec


class TestRunEvals:
    def test_all_builtin_cases_green(self):
        """核心契约:内置评测全绿——编排/质量检查/自学习链路端到端仍守约。"""
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

    def test_report_has_dimension_scorecard_and_release_verdict(self):
        report = run_evals(["gates_enforcement", "toolloop_discipline", "langgraph_path"])
        assert report["score"] == 100.0
        assert report["release_verdict"] is True
        assert report["dimensions"]["学术规范"]["score"] == 100.0
        assert report["dimensions"]["安全与可控"]["score"] == 100.0
        assert report["dimensions"]["LangGraph 路径"]["score"] == 100.0
        assert report["release_threshold"] == 90

    def test_continuous_task_case_is_registered_and_passes(self):
        report = run_evals(["continuous_tasks"])
        assert report["all_passed"] is True
        assert report["cases"]["continuous_tasks"]["total"] >= 4

    def test_langgraph_path_case_is_registered_and_passes(self):
        report = run_evals(["langgraph_path"])
        assert report["all_passed"] is True
        assert report["cases"]["langgraph_path"]["total"] == 3

    def test_critical_dimension_failure_blocks_release(self, monkeypatch):
        def failing(_tmp):
            return [{"name": "故意失败", "passed": False, "detail": "fixture"}]
        monkeypatch.setitem(CASES, "gates_enforcement", (failing, "fixture"))
        report = run_evals(["gates_enforcement"])
        assert report["score"] == 0.0
        assert report["release_verdict"] is False
        assert report["dimensions"]["学术规范"]["score"] == 0.0

    def test_agent_case_spec_rejects_single_turn_tasks(self):
        ok, reasons = validate_agent_case_spec({
            "min_model_turns": 1,
            "min_tool_calls": 0,
            "requires_verification": False,
            "checks": ["text"],
        })
        assert ok is False
        assert len(reasons) >= 3

    def test_agent_case_spec_accepts_multiturn_orchestration_task(self):
        ok, reasons = validate_agent_case_spec({
            "min_model_turns": 2,
            "min_tool_calls": 2,
            "requires_verification": True,
            "expected_tools": ["lit_search", "save_file"],
            "checks": ["dependency_receipt", "artifact_exists"],
        })
        assert ok is True and reasons == []


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

    def test_scorecard_prints_dimensions_and_verdict(self):
        out = format_report(run_evals(["gates_enforcement", "toolloop_discipline", "langgraph_path"]))
        assert "加权总分" in out and "学术规范" in out and "发布判定: 可发布" in out


class TestCliEval:
    def test_cli_eval_writes_report_and_exits_zero(self, tmp_path, monkeypatch, capsys):
        from psyclaw import cli
        monkeypatch.chdir(tmp_path)
        rc = cli.main(["eval", "--case", "lit_screen"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "lit_screen" in out
        saved = json.loads(Path("deliverables/eval_report.json").read_text(encoding="utf-8"))
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
class TestEvalOutputRobustness:
    """feat-084(评审修复):GBK 管道不崩、报告先落盘、--json 纯净、重复用例去重。"""
    def test_duplicate_case_ids_deduped(self):
        r = run_evals(["error_learning", "error_learning"])
        assert list(r["cases"]) == ["error_learning"]
        assert r["total"] == r["cases"]["error_learning"]["total"]  # 合计=分项
    def test_print_encoding_safe_survives_gbk(self, capsys):
        """✅/❌ 在 GBK stdout 下降级替换而非 UnicodeEncodeError(中文 Windows 管道)。"""
        import io
        import sys as _sys
        from psyclaw.cli import _print_encoding_safe
        buf = io.TextIOWrapper(io.BytesIO(), encoding="gbk")
        old = _sys.stdout
        _sys.stdout = buf
        try:
            _print_encoding_safe("✅ gates_enforcement(4/4)—质量检查")
        finally:
            _sys.stdout = old
        buf.seek(0)
        assert "质量检查" in buf.buffer.getvalue().decode("gbk")  # 中文保留,不崩
    def test_report_written_even_if_print_crashes(self, tmp_path, monkeypatch, capsys):
        """落盘先于打印:打印层崩溃也不能吞掉报告工件。"""
        from psyclaw import cli
        monkeypatch.chdir(tmp_path)
        calls = {"n": 0}
        def boom(_s):
            calls["n"] += 1
            raise RuntimeError("print 层意外")
        monkeypatch.setattr(cli, "_print_encoding_safe", boom)
        try:
            cli.main(["eval", "--case", "error_learning"])
        except RuntimeError:
            pass
        assert calls["n"] == 1
        assert (tmp_path / "deliverables" / "eval_report.json").exists()
    def test_json_stdout_stays_pure_when_save_fails(self, tmp_path, monkeypatch, capsys):
        """--json 时落盘失败的提示走 stderr,stdout 仍是可解析 JSON。"""
        from psyclaw import cli
        monkeypatch.chdir(tmp_path)
        ro = tmp_path / "deliverables"
        ro.write_text("挡路的文件", encoding="utf-8")   # 同名文件令 mkdir 失败
        rc = cli.main(["eval", "--case", "error_learning", "--json"])
        assert rc == 0
        captured = capsys.readouterr()
        json.loads(captured.out)                        # stdout 纯 JSON
        assert "落盘失败" in captured.err
