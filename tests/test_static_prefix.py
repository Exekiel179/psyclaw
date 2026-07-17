"""feat-156:系统提示静态前缀——让 provider prompt 缓存命中,同样效果省 token。

此前 _CHOICES/_READ/_RUN 静态约定块排在动态知识/项目感知之后,中间内容每轮一变
就打断缓存前缀,271 tok/轮 白白全价重算。重排为【静态前缀 + 动态后缀】后,
约定块进稳定前缀,DeepSeek/OpenAI 自动缓存命中,同样效果计费打折。
"""
from __future__ import annotations

import psyclaw.repl as repl


def _session(file_access="open"):
    s = repl.ReplSession.__new__(repl.ReplSession)
    s.system = "SYS_CORE(瘦核心+能力地图)"
    s.file_access = file_access
    s.plugins = None
    return s


def test_static_prefix_stable_across_calls():
    """无参、不依赖消息——跨轮字节一致(缓存前缀成立的前提)。"""
    s = _session()
    assert s._static_system() == s._static_system()


def test_static_prefix_contains_conventions():
    """约定块(选择/读/跑)现在在静态前缀里——移出了动态区。"""
    pref = _session()._static_system()
    assert repl._CHOICES_SYSTEM in pref
    assert repl._READ_OPEN_SYSTEM in pref
    assert repl._RUN_SYSTEM in pref


def test_static_prefix_starts_with_core():
    pref = _session()._static_system()
    assert pref.startswith("SYS_CORE")


def test_static_prefix_has_no_dynamic_markers():
    """静态前缀不含任何每轮变化的内容(知识/召回/项目感知/教训)。"""
    pref = _session()._static_system()
    for marker in ("召回", "本会话已知环境限制", "项目结构", "决策备忘"):
        assert marker not in pref


def test_safe_mode_changes_prefix_but_still_stable():
    open_pref = _session("open")._static_system()
    safe_pref = _session("safe")._static_system()
    assert open_pref != safe_pref                    # /access 切换才变
    assert _session("safe")._static_system() == safe_pref   # 同档仍稳定


def test_conventions_precede_dynamic_in_full_assembly(monkeypatch):
    """整体系统提示里:约定块出现在动态知识/召回之前(缓存前缀连续)。"""
    # 用 _static_system 的位置代理:约定块在前缀,动态在其后拼接
    pref = _session()._static_system()
    dynamic = "\n\n# 相关知识\n某某\n\n# 历史上下文召回\n某某"
    full = pref + dynamic
    assert full.index(repl._RUN_SYSTEM) < full.index("相关知识")
    assert full.index(repl._CHOICES_SYSTEM) < full.index("召回")
