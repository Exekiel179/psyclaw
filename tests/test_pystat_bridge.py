"""workflow 分析步接 pystat MCP(v0.10 feat-053)——纯映射 + 注入客户端,离线可测。"""
from __future__ import annotations

from psyclaw.workflows import pystat_bridge as PB


# --- rec_to_pystat_call(纯映射) ------------------------------------------------

def test_map_ttest():
    call = PB.rec_to_pystat_call({"analysis": "ttest", "dv": "rt", "group": "cond"}, "d.csv")
    assert call == ("pystat_ttest", {"csv_path": "d.csv", "dv": "rt", "group": "cond"})


def test_map_anova_group_to_between():
    call = PB.rec_to_pystat_call({"analysis": "anova", "dv": "y", "group": "grp"}, "d.csv")
    assert call == ("pystat_anova", {"csv_path": "d.csv", "dv": "y", "between": "grp"})


def test_map_regression_iv_joined():
    call = PB.rec_to_pystat_call({"analysis": "regression", "dv": "y",
                                  "iv": ["x1", "x2", "x3"]}, "d.csv")
    assert call == ("pystat_regression",
                    {"csv_path": "d.csv", "dv": "y", "predictors": "x1,x2,x3"})


def test_map_correlation():
    call = PB.rec_to_pystat_call({"analysis": "correlation", "x": "a", "y": "b"}, "d.csv")
    assert call == ("pystat_correlation", {"csv_path": "d.csv", "x": "a", "y": "b"})


def test_map_descriptives():
    call = PB.rec_to_pystat_call({"analysis": "descriptives"}, "d.csv")
    assert call == ("pystat_describe", {"csv_path": "d.csv"})


def test_map_unknown_returns_none():
    assert PB.rec_to_pystat_call({"analysis": "mystery"}, "d.csv") is None
    assert PB.rec_to_pystat_call({}, "d.csv") is None


# --- run_via_pystat(注入 fake 客户端) -----------------------------------------

class _FakeClient:
    def __init__(self, result="结果文本", boom=False):
        self._result = result
        self._boom = boom
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def call_tool(self, name, args):
        if self._boom:
            raise RuntimeError("mcp down")
        self.calls.append((name, args))
        return self._result


def test_run_via_pystat_calls_correct_tool():
    fc = _FakeClient(result="t=2.1, d=0.5, CI95=[...]")
    out = PB.run_via_pystat({"analysis": "ttest", "dv": "rt", "group": "cond"},
                            "d.csv", client_factory=lambda: fc)
    assert out == "t=2.1, d=0.5, CI95=[...]"
    assert fc.calls == [("pystat_ttest",
                         {"csv_path": "d.csv", "dv": "rt", "group": "cond"})]


def test_run_via_pystat_no_client_returns_none():
    out = PB.run_via_pystat({"analysis": "ttest", "dv": "y", "group": "g"},
                            "d.csv", client_factory=lambda: None)
    assert out is None


def test_run_via_pystat_unmappable_returns_none():
    called = []
    PB.run_via_pystat({"analysis": "mystery"}, "d.csv",
                      client_factory=lambda: called.append(1))
    assert called == []          # 不可映射时根本不建客户端


def test_run_via_pystat_exception_is_swallowed():
    out = PB.run_via_pystat({"analysis": "descriptives"}, "d.csv",
                            client_factory=lambda: _FakeClient(boom=True))
    assert out is None


def test_run_via_pystat_empty_result_is_none():
    out = PB.run_via_pystat({"analysis": "descriptives"}, "d.csv",
                            client_factory=lambda: _FakeClient(result=""))
    assert out is None


# --- step_analysis 端到端(注入桩,tmp 工程) -----------------------------------

def test_step_analysis_writes_result_when_pystat_runs(tmp_path, monkeypatch):
    import types
    from psyclaw.workflows import steps_analysis as SA

    # 造最小 CSV(两组 + 连续列 → 推荐 ttest)
    csv = tmp_path / "d.csv"
    csv.write_text("cond,rt\nA,1.0\nA,1.2\nB,2.0\nB,2.3\n", encoding="utf-8")

    ctx = types.SimpleNamespace(
        data={"data_csv": str(csv)}, artifacts={}, project=tmp_path)
    ctx.data["profile"] = SA.profile_data(str(csv))

    # 注入:pystat 桥直接返回结果(不起真 MCP)
    monkeypatch.setattr("psyclaw.workflows.pystat_bridge.run_via_pystat",
                        lambda rec, path: "PYSTAT 结果:t=..., d=..., CI95=[...]")

    out = SA.step_analysis(ctx)
    assert out["ran_via_pystat"] is True
    res = tmp_path / "outputs" / "analysis_result.txt"
    assert res.exists() and "PYSTAT" in res.read_text(encoding="utf-8")
    assert (tmp_path / "outputs" / "analysis.py").exists()   # 脚本仍照写


def test_step_analysis_survives_pystat_unavailable(tmp_path, monkeypatch):
    import types
    from psyclaw.workflows import steps_analysis as SA

    csv = tmp_path / "d.csv"
    csv.write_text("cond,rt\nA,1.0\nB,2.0\nA,1.1\nB,2.1\n", encoding="utf-8")
    ctx = types.SimpleNamespace(
        data={"data_csv": str(csv)}, artifacts={}, project=tmp_path)
    ctx.data["profile"] = SA.profile_data(str(csv))

    # pystat 不可用 → 返回 None;step 不应报错,脚本照旧
    monkeypatch.setattr("psyclaw.workflows.pystat_bridge.run_via_pystat",
                        lambda rec, path: None)
    out = SA.step_analysis(ctx)
    assert out["ran_via_pystat"] is False
    assert (tmp_path / "outputs" / "analysis.py").exists()
    assert not (tmp_path / "outputs" / "analysis_result.txt").exists()
def test_real_result_guard():
    assert PB._real_result(None) is None
    assert PB._real_result("") is None
    assert PB._real_result("统计库未安装(pip install …)。脚本骨架:\n```python\n…") is None
    assert PB._real_result('{"pooled_effect": 0.38}') == '{"pooled_effect": 0.38}'
def test_run_via_pystat_script_skeleton_not_treated_as_result():
    out = PB.run_via_pystat(
        {"analysis": "descriptives"}, "d.csv",
        client_factory=lambda: _FakeClient(result="统计库未安装(...)。脚本骨架:..."))
    assert out is None
def test_run_meta_via_pystat_calls_tool():
    fc = _FakeClient(result='{"pooled_effect": 0.38, "ci95": [0.24, 0.52]}')
    out = PB.run_meta_via_pystat("effects.csv", client_factory=lambda: fc)
    assert out and "pooled_effect" in out
    assert fc.calls == [("pystat_meta", {"csv_path": "effects.csv"})]
def test_run_meta_via_pystat_failsafe():
    assert PB.run_meta_via_pystat("e.csv", client_factory=lambda: None) is None
    assert PB.run_meta_via_pystat(
        "e.csv", client_factory=lambda: _FakeClient(boom=True)) is None
_EFFECTS = "study,d,se\nA,0.4,0.15\nB,0.3,0.12\nC,0.5,0.2\n"
def _meta_ctx(tmp_path):
    import types
    from psyclaw.workflows import steps_meta as SM
    csv = tmp_path / "effects.csv"
    csv.write_text(_EFFECTS, encoding="utf-8")
    ctx = types.SimpleNamespace(data={"effects_csv": str(csv)}, artifacts={},
                                project=tmp_path, clar="(无)", topic="正念元分析",
                                provider=None)
    ctx.data["effects_info"] = SM.validate_effects(str(csv))
    return ctx
def test_step_meta_script_writes_result_when_pystat_runs(tmp_path, monkeypatch):
    from psyclaw.workflows import steps_meta as SM
    ctx = _meta_ctx(tmp_path)
    monkeypatch.setattr("psyclaw.workflows.pystat_bridge.run_meta_via_pystat",
                        lambda path: '{"pooled_effect": 0.38, "i2_percent": 12.0}')
    out = SM.step_meta_script(ctx)
    assert out["ran_via_pystat"] is True
    res = tmp_path / "outputs" / "meta_result.txt"
    assert res.exists() and "pooled_effect" in res.read_text(encoding="utf-8")
    assert (tmp_path / "outputs" / "meta_analysis.py").exists()   # 脚本仍照写
def test_step_meta_script_survives_pystat_unavailable(tmp_path, monkeypatch):
    from psyclaw.workflows import steps_meta as SM
    ctx = _meta_ctx(tmp_path)
    monkeypatch.setattr("psyclaw.workflows.pystat_bridge.run_meta_via_pystat",
                        lambda path: None)
    out = SM.step_meta_script(ctx)
    assert out["ran_via_pystat"] is False
    assert not (tmp_path / "outputs" / "meta_result.txt").exists()
def test_step_write_meta_injects_real_result(tmp_path, monkeypatch):
    from psyclaw.output import writing_backend
    from psyclaw.workflows import steps_meta as SM
    ctx = _meta_ctx(tmp_path)
    ctx.data["meta_result"] = '{"pooled_effect": 0.38, "ci95": [0.24, 0.52]}'
    seen = {}
    def _fake_write(topic, context, provider, project):
        seen["context"] = context
        return "稿件正文", {}
    monkeypatch.setattr(writing_backend, "write_paper", _fake_write)
    SM.step_write_meta(ctx)
    assert "实际元分析结果" in seen["context"]
    assert "0.38" in seen["context"]              # 真实数值确实进了写作上下文
def test_step_write_meta_without_result_keeps_old_context(tmp_path, monkeypatch):
    from psyclaw.output import writing_backend
    from psyclaw.workflows import steps_meta as SM
    ctx = _meta_ctx(tmp_path)
    seen = {}
    monkeypatch.setattr(writing_backend, "write_paper",
                        lambda t, c, p, pr: (seen.update(context=c) or "稿件", {}))
    SM.step_write_meta(ctx)
    assert "实际元分析结果" not in seen["context"]   # 没跑出结果就不假装有
def test_step_write_analysis_injects_real_result(tmp_path, monkeypatch):
    import types
    from psyclaw.output import writing_backend
    from psyclaw.workflows import steps_analysis as SA
    ctx = types.SimpleNamespace(
        data={"analysis_rec": {"analysis": "ttest", "rationale": "二分类+连续"},
              "analysis_result": "T=3.2, p=.004, d=0.81, CI95=[0.3, 1.3]"},
        artifacts={}, project=tmp_path, clar="(无)", topic="RT 组间差异",
        provider=None)
    seen = {}
    monkeypatch.setattr(writing_backend, "write_paper",
                        lambda t, c, p, pr: (seen.update(context=c) or "稿件", {}))
    SA.step_write_analysis(ctx)
    assert "实际分析结果" in seen["context"] and "d=0.81" in seen["context"]
def test_pystat_meta_offline_returns_script_not_fake_numbers(tmp_path):
    """本测试环境未装 statsmodels → 必须返回脚本骨架,绝不假装算出结果。"""
    import pytest
    try:
        import statsmodels  # noqa: F401
        pytest.skip("本环境装了 statsmodels,离线路径不适用")
    except ImportError:
        pass
    from psyclaw.mcp.servers.pystat_server import pystat_meta
    csv = tmp_path / "effects.csv"
    csv.write_text(_EFFECTS, encoding="utf-8")
    out = pystat_meta({"csv_path": str(csv)})
    assert "统计库未安装" in out and "combine_effects" in out
def test_pystat_meta_invalid_csv_fails_closed(tmp_path):
    from psyclaw.mcp.servers.pystat_server import pystat_meta
    csv = tmp_path / "bad.csv"
    csv.write_text("a,b\n1,2\n", encoding="utf-8")
    out = pystat_meta({"csv_path": str(csv)})
    assert "校验失败" in out
