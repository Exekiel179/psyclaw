"""一键环境配置测试(v0.9 feat-051)——依赖注入,离线不联网。"""
from __future__ import annotations

from psyclaw import env_setup as ES


def _detect(stats_ready=True, full_ready=True):
    def _fn():
        return {"groups": {
            "stats": {"ready": stats_ready,
                      "missing": [] if stats_ready else [("pingouin", "pingouin"),
                                                         ("pandas", "pandas")]},
            "full": {"ready": full_ready,
                     "missing": [] if full_ready else [("prompt_toolkit", "prompt_toolkit")]},
        }, "bins": {}}
    return _fn


def _conf(source="/home/u/.psyclaw/config.yaml"):
    return lambda: {"provider": "deepseek", "_source": source}


def _prov(name="deepseek", key="k"):
    class P:
        pass
    p = P()
    p.name = name
    p.api_key = key
    return lambda conf: p


# --- diagnose ----------------------------------------------------------------

def test_diagnose_all_ok():
    checks = ES.diagnose(detect_fn=_detect(), config_fn=_conf(), provider_fn=_prov())
    assert {c["key"] for c in checks} == {"config", "provider", "stats", "full"}
    assert all(c["ok"] for c in checks)


def test_diagnose_missing_config_and_key():
    checks = ES.diagnose(detect_fn=_detect(), config_fn=_conf("(defaults)"),
                         provider_fn=_prov(name="mock", key=""))
    by = {c["key"]: c for c in checks}
    assert by["config"]["ok"] is False and "psyclaw config" in by["config"]["fix"]
    assert by["provider"]["ok"] is False and by["provider"]["auto"] is False
    assert "mock" in by["provider"]["detail"]


def test_diagnose_missing_groups_are_auto():
    checks = ES.diagnose(detect_fn=_detect(stats_ready=False, full_ready=False),
                         config_fn=_conf(), provider_fn=_prov())
    by = {c["key"]: c for c in checks}
    assert by["stats"]["ok"] is False and by["stats"]["auto"] is True
    assert "pingouin" in by["stats"]["detail"]
    assert by["full"]["auto"] is True


def test_provider_exception_marked_not_ok():
    def _boom(conf):
        raise RuntimeError("provider broken")
    checks = ES.diagnose(detect_fn=_detect(), config_fn=_conf(), provider_fn=_boom)
    prov = next(c for c in checks if c["key"] == "provider")
    assert prov["ok"] is False


# --- plan_installs -----------------------------------------------------------

def test_plan_installs_only_auto_missing():
    checks = ES.diagnose(detect_fn=_detect(stats_ready=False, full_ready=True),
                         config_fn=_conf("(defaults)"), provider_fn=_prov(name="mock", key=""))
    # config/provider 缺但非 auto → 不计划;只有 stats 缺且 auto
    assert ES.plan_installs(checks) == ["stats"]


def test_plan_installs_empty_when_ready():
    checks = ES.diagnose(detect_fn=_detect(), config_fn=_conf(), provider_fn=_prov())
    assert ES.plan_installs(checks) == []


# --- bootstrap ---------------------------------------------------------------

def test_bootstrap_no_apply_reports_plan_no_install():
    res = ES.bootstrap(detect_fn=_detect(stats_ready=False), config_fn=_conf(),
                       provider_fn=_prov(), apply=False)
    assert res["planned"] == ["stats"]
    assert res["installed"] == {}          # 未 apply,不装
    assert res["all_ok"] is False


def test_bootstrap_apply_installs_and_rechecks():
    """apply=True:调 installer 装缺失组;重诊断反映安装后状态。"""
    state = {"stats": False}
    calls = []

    def _installer(groups):
        calls.append(list(groups))
        for g in groups:
            state[g] = True          # 模拟装成功
        return {g: True for g in groups}

    # detect 随 state 变化(第一次缺、装后就绪)
    def _dyn_detect():
        return {"groups": {
            "stats": {"ready": state["stats"],
                      "missing": [] if state["stats"] else [("pingouin", "pingouin")]},
            "full": {"ready": True, "missing": []},
        }, "bins": {}}

    res = ES.bootstrap(detect_fn=_dyn_detect, config_fn=_conf(), provider_fn=_prov(),
                       apply=True, installer=_installer)
    assert calls == [["stats"]]
    assert res["installed"] == {"stats": True}
    assert res["all_ok"] is True           # 重诊断后 stats 就绪


def test_bootstrap_install_failure_is_reported_not_raised():
    def _bad_installer(groups):
        raise RuntimeError("pip exploded")
    res = ES.bootstrap(detect_fn=_detect(stats_ready=False), config_fn=_conf(),
                       provider_fn=_prov(), apply=True, installer=_bad_installer)
    assert res["installed"].get("stats") is False
    assert "_error" in res["installed"]
    assert res["all_ok"] is False          # 不抛,如实报失败


def test_bootstrap_manual_lists_non_auto():
    res = ES.bootstrap(detect_fn=_detect(), config_fn=_conf("(defaults)"),
                       provider_fn=_prov(name="mock", key=""), apply=False)
    manual_keys = {c["key"] for c in res["manual"]}
    assert "config" in manual_keys and "provider" in manual_keys


# --- format_report -----------------------------------------------------------

def test_format_report_readable():
    res = ES.bootstrap(detect_fn=_detect(stats_ready=False), config_fn=_conf(),
                       provider_fn=_prov(), apply=False)
    rep = ES.format_report(res)
    assert "基础环境检查" in rep and "✗" in rep and "统计后端" in rep
    assert "环境状态" in rep
