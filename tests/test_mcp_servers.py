"""测试 E-2: Mplus / Stata MCP 语法生成服务器。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# --------------------------------------------------------------------------
# 导入辅助
# --------------------------------------------------------------------------

def _mplus():
    from psyclaw.mcp.servers.mplus_server import mplus_syntax, mplus_run
    return mplus_syntax, mplus_run


def _stata():
    from psyclaw.mcp.servers.stata_server import stata_dofile, stata_run
    return stata_dofile, stata_run


# ==========================================================================
# Mplus 语法生成
# ==========================================================================

class TestMplusSyntax:

    def test_cfa_basic(self):
        mplus_syntax, _ = _mplus()
        out = mplus_syntax({"analysis": "cfa",
                            "factors": "F1:x1 x2 x3",
                            "indicators": "x1 x2 x3"})
        assert "CFA" in out or "验证性" in out
        assert "F1 BY x1 x2 x3" in out
        assert "STANDARDIZED" in out
        assert "MODINDICES" in out

    def test_cfa_two_factors(self):
        mplus_syntax, _ = _mplus()
        out = mplus_syntax({"analysis": "cfa",
                            "factors": "F1:x1 x2 x3,F2:y1 y2 y3",
                            "indicators": "x1 x2 x3 y1 y2 y3"})
        assert "F1 BY x1 x2 x3" in out
        assert "F2 BY y1 y2 y3" in out

    def test_cfa_estimator_passed(self):
        mplus_syntax, _ = _mplus()
        out = mplus_syntax({"analysis": "cfa",
                            "factors": "F:v1 v2 v3",
                            "estimator": "WLSMV"})
        assert "WLSMV" in out

    def test_cfa_missing_code(self):
        mplus_syntax, _ = _mplus()
        out = mplus_syntax({"analysis": "cfa",
                            "factors": "F:v1 v2",
                            "missing": "-99"})
        assert "-99" in out

    def test_cfa_data_file(self):
        mplus_syntax, _ = _mplus()
        out = mplus_syntax({"analysis": "cfa",
                            "factors": "F:v1 v2",
                            "data_file": "mydata.dat"})
        assert "mydata.dat" in out

    def test_sem_basic(self):
        mplus_syntax, _ = _mplus()
        out = mplus_syntax({"analysis": "sem",
                            "factors": "F1:x1 x2 x3,F2:y1 y2 y3",
                            "structural": "F2 ON F1"})
        assert "F1 BY x1 x2 x3" in out
        assert "F2 BY y1 y2 y3" in out
        assert "F2 ON F1" in out

    def test_sem_no_structural_auto_path(self):
        mplus_syntax, _ = _mplus()
        out = mplus_syntax({"analysis": "sem",
                            "factors": "A:a1 a2,B:b1 b2"})
        assert "B ON A" in out

    def test_sem_output_cinterval(self):
        mplus_syntax, _ = _mplus()
        out = mplus_syntax({"analysis": "sem",
                            "factors": "F:v1 v2,G:v3 v4"})
        assert "CINTERVAL" in out

    def test_lgm_basic(self):
        mplus_syntax, _ = _mplus()
        out = mplus_syntax({"analysis": "lgm",
                            "time_points": "t1 t2 t3 t4"})
        assert "i s |" in out
        assert "t1@0" in out
        assert "t4@3" in out

    def test_lgm_three_waves(self):
        mplus_syntax, _ = _mplus()
        out = mplus_syntax({"analysis": "lgm",
                            "time_points": "w1,w2,w3"})
        assert "w1@0" in out
        assert "w3@2" in out

    def test_mixture_basic(self):
        mplus_syntax, _ = _mplus()
        out = mplus_syntax({"analysis": "mixture",
                            "indicators": "v1 v2 v3",
                            "n_classes": 3})
        assert "TYPE = MIXTURE" in out
        assert "CLASSES = c(3)" in out
        assert "TECH11" in out
        assert "TECH14" in out

    def test_mixture_two_classes_default(self):
        mplus_syntax, _ = _mplus()
        out = mplus_syntax({"analysis": "mixture",
                            "indicators": "a b c"})
        assert "c(2)" in out

    def test_mixture_gmm_with_time_points(self):
        mplus_syntax, _ = _mplus()
        out = mplus_syntax({"analysis": "mixture",
                            "time_points": "t1 t2 t3",
                            "n_classes": 2})
        assert "i s |" in out

    def test_unknown_analysis(self):
        mplus_syntax, _ = _mplus()
        out = mplus_syntax({"analysis": "invalid"})
        assert "未收录" in out
        assert "cfa" in out

    def test_no_mplus_exe_footer(self, monkeypatch):
        import psyclaw.mcp.servers.mplus_server as mod
        monkeypatch.setattr(mod, "_mplus_exe", lambda: None)
        out = mod.mplus_syntax({"analysis": "cfa", "factors": "F:v1 v2"})
        assert "未检测到" in out

    def test_mplus_exe_footer(self, monkeypatch):
        import psyclaw.mcp.servers.mplus_server as mod
        monkeypatch.setattr(mod, "_mplus_exe", lambda: "/usr/bin/mplus")
        out = mod.mplus_syntax({"analysis": "cfa", "factors": "F:v1 v2"})
        assert "/usr/bin/mplus" in out

    def test_mplus_run_no_exe(self, monkeypatch):
        import psyclaw.mcp.servers.mplus_server as mod
        _, mplus_run = _mplus()
        monkeypatch.setattr(mod, "_mplus_exe", lambda: None)
        out = mplus_run({})
        assert "未找到" in out

    def test_mplus_run_no_args(self, monkeypatch):
        import psyclaw.mcp.servers.mplus_server as mod
        _, mplus_run = _mplus()
        monkeypatch.setattr(mod, "_mplus_exe", lambda: "/fake/mplus")
        out = mplus_run({})
        assert "需提供" in out


# ==========================================================================
# Stata do-file 生成
# ==========================================================================

class TestStataDofile:

    def test_regression_basic(self):
        stata_dofile, _ = _stata()
        out = stata_dofile({"analysis": "regression", "dv": "y", "iv": "x"})
        assert "regress y x" in out
        assert "robust" in out
        assert "VIF" in out

    def test_regression_controls(self):
        stata_dofile, _ = _stata()
        out = stata_dofile({"analysis": "regression",
                            "dv": "score", "iv": "treat",
                            "controls": "age female"})
        assert "regress score treat age female" in out

    def test_regression_cluster_se(self):
        stata_dofile, _ = _stata()
        out = stata_dofile({"analysis": "regression",
                            "dv": "y", "iv": "x",
                            "cluster": "school"})
        assert "vce(cluster school)" in out

    def test_regression_data_file_dta(self):
        stata_dofile, _ = _stata()
        out = stata_dofile({"analysis": "regression",
                            "dv": "y", "iv": "x",
                            "data_file": "mydata.dta"})
        assert 'use "mydata.dta"' in out

    def test_regression_data_file_csv(self):
        stata_dofile, _ = _stata()
        out = stata_dofile({"analysis": "regression",
                            "dv": "y", "iv": "x",
                            "data_file": "mydata.csv"})
        assert "import delimited" in out

    def test_panel_basic(self):
        stata_dofile, _ = _stata()
        out = stata_dofile({"analysis": "panel",
                            "dv": "y", "iv": "x",
                            "panel_id": "id", "panel_time": "year"})
        assert "xtset id year" in out
        assert "xtreg y x, fe" in out
        assert "xtreg y x, re" in out
        assert "hausman" in out

    def test_panel_icc(self):
        stata_dofile, _ = _stata()
        out = stata_dofile({"analysis": "panel",
                            "dv": "y", "iv": "x"})
        assert "ICC" in out or "sigma_u" in out

    def test_iv_basic(self):
        stata_dofile, _ = _stata()
        out = stata_dofile({"analysis": "iv",
                            "dv": "y", "endog": "x",
                            "instruments": "z"})
        assert "ivregress 2sls" in out
        assert "(x = z)" in out
        assert "firststage" in out
        assert "endogenous" in out

    def test_iv_overid(self):
        stata_dofile, _ = _stata()
        out = stata_dofile({"analysis": "iv",
                            "dv": "y", "endog": "x",
                            "instruments": "z1 z2"})
        assert "overid" in out

    def test_logistic_basic(self):
        stata_dofile, _ = _stata()
        out = stata_dofile({"analysis": "logistic",
                            "dv": "outcome", "iv": "treat"})
        assert "logit outcome treat" in out
        assert "margins, dydx" in out
        assert "lroc" in out

    def test_logistic_or(self):
        stata_dofile, _ = _stata()
        out = stata_dofile({"analysis": "logistic",
                            "dv": "y", "iv": "x"})
        assert "or" in out

    def test_survival_basic(self):
        stata_dofile, _ = _stata()
        out = stata_dofile({"analysis": "survival",
                            "dv": "y", "iv": "group",
                            "time_var": "surv_time",
                            "event_var": "died"})
        assert "stset surv_time" in out
        assert "failure(died==1)" in out
        assert "stcox" in out
        assert "phtest" in out

    def test_survival_km(self):
        stata_dofile, _ = _stata()
        out = stata_dofile({"analysis": "survival",
                            "dv": "y", "iv": "arm",
                            "time_var": "t", "event_var": "event"})
        assert "sts graph" in out
        assert "sts test" in out

    def test_poisson_basic(self):
        stata_dofile, _ = _stata()
        out = stata_dofile({"analysis": "poisson",
                            "dv": "count", "iv": "x"})
        assert "poisson count x" in out
        assert "irr" in out
        assert "nbreg" in out

    def test_poisson_zero_inflation(self):
        stata_dofile, _ = _stata()
        out = stata_dofile({"analysis": "poisson",
                            "dv": "cnt", "iv": "x"})
        assert "zip" in out

    def test_unknown_analysis(self):
        stata_dofile, _ = _stata()
        out = stata_dofile({"analysis": "bogus"})
        assert "未收录" in out
        assert "regression" in out

    def test_no_stata_exe_footer(self, monkeypatch):
        import psyclaw.mcp.servers.stata_server as mod
        monkeypatch.setattr(mod, "_stata_exe", lambda: None)
        out = mod.stata_dofile({"analysis": "regression", "dv": "y", "iv": "x"})
        assert "未检测到" in out

    def test_stata_exe_footer(self, monkeypatch):
        import psyclaw.mcp.servers.stata_server as mod
        monkeypatch.setattr(mod, "_stata_exe", lambda: "/usr/local/bin/stata")
        out = mod.stata_dofile({"analysis": "regression", "dv": "y", "iv": "x"})
        assert "/usr/local/bin/stata" in out

    def test_stata_run_no_exe(self, monkeypatch):
        import psyclaw.mcp.servers.stata_server as mod
        _, stata_run = _stata()
        monkeypatch.setattr(mod, "_stata_exe", lambda: None)
        out = stata_run({})
        assert "未找到" in out

    def test_stata_run_no_args(self, monkeypatch):
        import psyclaw.mcp.servers.stata_server as mod
        _, stata_run = _stata()
        monkeypatch.setattr(mod, "_stata_exe", lambda: "/fake/stata")
        out = stata_run({})
        assert "需提供" in out


# ==========================================================================
# CLI 集成: cmd_mcp 选择新服务器
# ==========================================================================

class TestMcpCli:

    def test_mcp_list_shows_mplus(self, capsys):
        from psyclaw.mcp.manager import list_mcp_catalog
        catalog = list_mcp_catalog()
        names = [m["name"] for m in catalog]
        assert "mplus-mcp" in names

    def test_mcp_list_shows_stata(self, capsys):
        from psyclaw.mcp.manager import list_mcp_catalog
        catalog = list_mcp_catalog()
        names = [m["name"] for m in catalog]
        assert "stata-mcp" in names

    def test_mplus_is_builtin_always(self):
        from psyclaw.mcp.manager import list_mcp_catalog
        catalog = {m["name"]: m for m in list_mcp_catalog()}
        assert catalog["mplus-mcp"]["enabled"] is True

    def test_stata_is_builtin_always(self):
        from psyclaw.mcp.manager import list_mcp_catalog
        catalog = {m["name"]: m for m in list_mcp_catalog()}
        assert catalog["stata-mcp"]["enabled"] is True

    def test_mcp_help_contains_mplus(self, capsys):
        from psyclaw.cli import cmd_mcp
        import argparse
        ns = argparse.Namespace(name=None)
        cmd_mcp(ns)
        out = capsys.readouterr().out
        assert "mplus" in out

    def test_mcp_help_contains_stata(self, capsys):
        from psyclaw.cli import cmd_mcp
        import argparse
        ns = argparse.Namespace(name=None)
        cmd_mcp(ns)
        out = capsys.readouterr().out
        assert "stata" in out


# ==========================================================================
# 无 pytest 自跑块
# ==========================================================================

if __name__ == "__main__":
    import io
    import inspect
    import traceback

    class _CapSys:
        """stdout 捕获替身，支持 readouterr()。"""
        def __init__(self):
            self._sio = io.StringIO()
            self._old = None
        def __enter__(self):
            self._old = sys.stdout
            sys.stdout = self._sio
            return self
        def __exit__(self, *_):
            sys.stdout = self._old
        def readouterr(self):
            class _R:
                pass
            r = _R()
            r.out = self._sio.getvalue()
            return r

    class _Monkeypatch:
        """setattr 替身，支持测试后撤销。"""
        def __init__(self):
            self._restores: list = []
        def setattr(self, obj, name, value):  # type: ignore[override]
            old = getattr(obj, name)
            builtins_setattr(obj, name, value)
            self._restores.append((obj, name, old))
        def undo(self):
            for obj, name, old in reversed(self._restores):
                builtins_setattr(obj, name, old)
            self._restores.clear()

    builtins_setattr = setattr

    _SUITES = [
        TestMplusSyntax,
        TestStataDofile,
        TestMcpCli,
    ]

    passed = failed = 0
    for suite_cls in _SUITES:
        suite = suite_cls()
        for mname in sorted(m for m in dir(suite_cls) if m.startswith("test_")):
            fn = getattr(suite, mname)
            params = inspect.signature(fn).parameters
            mp = _Monkeypatch()
            cap = _CapSys()
            kwargs: dict = {}
            if "monkeypatch" in params:
                kwargs["monkeypatch"] = mp
            if "capsys" in params:
                kwargs["capsys"] = cap
            try:
                if "capsys" in params:
                    with cap:
                        fn(**kwargs)
                else:
                    fn(**kwargs)
                passed += 1
                print(f"  PASS  {suite_cls.__name__}.{mname}")
            except Exception as exc:
                failed += 1
                print(f"  FAIL  {suite_cls.__name__}.{mname}")
                traceback.print_exc()
            finally:
                mp.undo()

    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
