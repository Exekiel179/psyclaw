"""feat:lit 自动调 WebBridge 进机构库(知网)检索,合并进公开 API 结果。

lit 只打公开 API(检不到知网/万方);此前只能提示用户手动走桥接。本模块让 psyclaw
自己驱动 WebBridge(用户已登录的真实浏览器):navigate 到知网检索 → evaluate 抽取
结果行 → 归一成 lit 题录 schema → 合并去重。全程 fail-safe:桥不可用/抽取失败都不抛,
降级回公开 API 结果 + 指路,绝不中断 lit。call 可注入,离线单测。
"""
from __future__ import annotations

from psyclaw.psych import litbridge


# ---- 可用性判定 --------------------------------------------------------------

def test_available_needs_binary_daemon_extension():
    ok, _ = litbridge.bridge_available(installed_fn=lambda: False,
                                       status_fn=lambda **k: None)
    assert ok is False
    ok, _ = litbridge.bridge_available(installed_fn=lambda: True,
                                       status_fn=lambda **k: None)
    assert ok is False                                   # 守护进程没起
    ok, _ = litbridge.bridge_available(installed_fn=lambda: True,
                                       status_fn=lambda **k: {"extension_connected": False})
    assert ok is False                                   # 扩展没连
    ok, reason = litbridge.bridge_available(installed_fn=lambda: True,
                                            status_fn=lambda **k: {"extension_connected": True})
    assert ok is True and reason == ""


# ---- URL 构造 ----------------------------------------------------------------

def test_cnki_search_url_encodes_query():
    u = litbridge.db_search_url("cnki", "公正世界信念")
    assert u.startswith("https://") and "cnki" in u
    assert "%E5%85%AC" in u or "公正世界信念" in u        # 编码或原样含查询


def test_unknown_db_url_empty():
    assert litbridge.db_search_url("no-such-db", "x") == ""


# ---- 结果解析 ----------------------------------------------------------------

def test_parse_normalizes_records():
    raw = [
        {"title": "公正世界信念：概念、测量、及研究热点", "authors": "杜建政;祝振兵",
         "year": "2007", "source": "心理科学进展"},
        {"title": "  ", "authors": "", "year": ""},       # 空标题剔除
    ]
    recs = litbridge.parse_bridge_results(raw, source="知网")
    assert len(recs) == 1
    r = recs[0]
    assert r["title"].startswith("公正世界信念")
    assert r["authors"] == ["杜建政", "祝振兵"]            # 分号/逗号拆分
    assert r["year"] == "2007"
    assert r["source"] == "知网"
    assert r["doi"] is None                               # 知网题录一般无 DOI
    assert "oa_status" in r                                # 补齐 schema 键


def test_parse_handles_wrapped_payload():
    # daemon evaluate 返回可能包一层 {"result": [...]} 或 JSON 字符串
    import json
    wrapped = {"result": [{"title": "T", "authors": "A", "year": "2020"}]}
    assert len(litbridge.parse_bridge_results(wrapped)) == 1
    as_str = json.dumps([{"title": "T", "authors": "A", "year": "2020"}])
    assert len(litbridge.parse_bridge_results(as_str)) == 1
    assert litbridge.parse_bridge_results(None) == []


# ---- 编排(注入 mock call)---------------------------------------------------

def _mock_call_ok(action, args=None, **k):
    if action == "navigate":
        return {"success": True}
    if action == "evaluate":
        return {"success": True, "result": [
            {"title": "公正世界信念研究", "authors": "张三;李四", "year": "2019",
             "source": "心理学报"}]}
    return {"success": True}


def test_bridge_search_returns_records():
    out = litbridge.bridge_search("公正世界信念", db="cnki", call=_mock_call_ok,
                                  available_fn=lambda **k: (True, ""))
    assert out["ok"] is True
    assert len(out["records"]) == 1
    assert out["records"][0]["source"]
    assert out["db"] == "cnki"


def test_db_set_for_query_by_language():
    assert litbridge.db_set_for_query("公正世界信念") == ["cnki", "wanfang", "vip"]
    assert litbridge.db_set_for_query("belief in a just world") == []


def test_resolve_dbs_aliases_and_unknown():
    valid, unknown = litbridge.resolve_dbs("知网,wanfang,维普", "x")
    assert valid == ["cnki", "wanfang", "vip"] and unknown == []
    valid, unknown = litbridge.resolve_dbs("cnki,foobar", "x")
    assert valid == ["cnki"] and unknown == ["foobar"]
    # None → 按查询语言
    assert litbridge.resolve_dbs(None, "公正世界信念")[0] == ["cnki", "wanfang", "vip"]
    # 去重
    assert litbridge.resolve_dbs("知网,cnki", "x")[0] == ["cnki"]


def test_vip_profile_present_and_js_valid():
    assert "vip" in litbridge._DB_PROFILES
    js = litbridge._extract_js("vip")
    assert "querySelectorAll" in js


def test_lit_cli_multi_db_loops_all(tmp_path, monkeypatch, capsys):
    from psyclaw.psych import litsearch, lit_cli as lc
    monkeypatch.setattr(litsearch, "search", _fake_search)
    monkeypatch.setattr(litbridge, "bridge_available", lambda **k: (True, ""))
    calls = []

    def _bs(q, db="cnki", **k):
        calls.append(db)
        return {"ok": True, "reason": "", "db": db, "name": litbridge._DB_PROFILES[db]["name"],
                "records": [{"title": f"{db}命中文献", "doi": None, "authors": ["作者"],
                             "year": "2020", "source": db, "oa_status": "unknown",
                             "oa_url": None, "abstract": "", "pmid": None,
                             "pmcid": None, "arxiv_id": None}]}
    monkeypatch.setattr(litbridge, "bridge_search", _bs)
    rc = lc.lit_cli("公正世界信念", project_dir=str(tmp_path), limit=10)
    assert rc == 0
    assert calls == ["cnki", "wanfang", "vip"]           # 三库都跑了
    out = capsys.readouterr().out
    assert "知网" in out and "万方" in out and "维普" in out


# ---- 首次没装 → 交互一键装(feat-173)----------------------------------------

def test_first_install_prompt_yes_installs(capsys):
    from psyclaw.psych import lit_cli as lc
    from psyclaw import ui
    installed = {"done": False}
    lc._first_install_nudge_or_hint(
        "公正世界信念", "WebBridge 未安装(psyclaw webbridge install)", ui,
        input_fn=lambda p: "y", is_tty=True, asked_fn=lambda: False,
        mark_fn=lambda: None, install_fn=lambda ui_: installed.__setitem__("done", True))
    assert installed["done"] is True


def test_first_install_prompt_no_shows_command(capsys):
    from psyclaw.psych import lit_cli as lc
    from psyclaw import ui
    called = {"install": False}
    lc._first_install_nudge_or_hint(
        "公正世界信念", "WebBridge 未安装(psyclaw webbridge install)", ui,
        input_fn=lambda p: "n", is_tty=True, asked_fn=lambda: False,
        mark_fn=lambda: None, install_fn=lambda ui_: called.__setitem__("install", True))
    assert called["install"] is False
    assert "webbridge install" in capsys.readouterr().out


def test_second_time_no_prompt_just_hint(capsys):
    from psyclaw.psych import lit_cli as lc
    from psyclaw import ui
    called = {"input": False}

    def _inp(p):
        called["input"] = True
        return "y"
    lc._first_install_nudge_or_hint(
        "公正世界信念", "WebBridge 未安装(psyclaw webbridge install)", ui,
        input_fn=_inp, is_tty=True, asked_fn=lambda: True,   # 已问过
        mark_fn=lambda: None, install_fn=lambda ui_: None)
    assert called["input"] is False                          # 不再追问
    assert "一步开启" in capsys.readouterr().out


def test_non_tty_never_prompts(capsys):
    from psyclaw.psych import lit_cli as lc
    from psyclaw import ui
    called = {"input": False}
    lc._first_install_nudge_or_hint(
        "公正世界信念", "WebBridge 未安装(psyclaw webbridge install)", ui,
        input_fn=lambda p: called.__setitem__("input", True) or "y",
        is_tty=False, asked_fn=lambda: False, mark_fn=lambda: None,
        install_fn=lambda ui_: None)
    assert called["input"] is False                          # 非交互绝不阻塞问询


def test_enable_command_maps_reason_to_step():
    assert litbridge.enable_command("WebBridge 未安装(psyclaw webbridge install)") \
        == "psyclaw webbridge install"
    assert litbridge.enable_command("WebBridge 守护进程未运行(psyclaw webbridge start)") \
        == "psyclaw webbridge start"
    assert litbridge.enable_command("浏览器扩展未连接(psyclaw webbridge status 查看)") \
        == "psyclaw webbridge status"
    assert litbridge.enable_command("") == "psyclaw webbridge install"


def test_lit_cli_auto_unavailable_gives_enable_step(tmp_path, monkeypatch, capsys):
    """默认(auto)桥不可用时:给一步开启指引,而非静默/泛化。"""
    from psyclaw.psych import litsearch, lit_cli as lc
    monkeypatch.setattr(litsearch, "search", _fake_search)
    monkeypatch.setattr(litbridge, "bridge_available",
                        lambda **k: (False, "WebBridge 未安装(psyclaw webbridge install)"))
    rc = lc.lit_cli("公正世界信念", project_dir=str(tmp_path), limit=10)   # 默认 auto
    assert rc == 0
    out = capsys.readouterr().out
    assert "psyclaw webbridge install" in out
    assert "无需 --bridge" in out


def test_bridge_search_unavailable_graceful():
    out = litbridge.bridge_search("x", available_fn=lambda **k: (False, "扩展未连接"))
    assert out["ok"] is False and out["records"] == []
    assert "扩展" in out["reason"]


def test_bridge_search_navigate_fails_graceful():
    def _call(action, args=None, **k):
        return {"success": False, "error": "boom"}
    out = litbridge.bridge_search("x", call=_call, available_fn=lambda **k: (True, ""))
    assert out["ok"] is False and out["records"] == []


def test_bridge_search_empty_extraction_graceful():
    def _call(action, args=None, **k):
        if action == "evaluate":
            return {"success": True, "result": []}
        return {"success": True}
    out = litbridge.bridge_search("x", call=_call, available_fn=lambda **k: (True, ""))
    assert out["ok"] is True and out["records"] == []     # 空抽取不算失败,但无记录


def test_bridge_search_never_raises():
    def _boom(action, args=None, **k):
        raise RuntimeError("network dead")
    out = litbridge.bridge_search("x", call=_boom, available_fn=lambda **k: (True, ""))
    assert out["ok"] is False and out["records"] == []


# ---- 合并去重 ----------------------------------------------------------------

def test_merge_dedups_by_title():
    api = [{"title": "公正世界信念：概念、测量、及研究热点", "doi": None, "authors": [],
            "year": "2007", "source": "OpenAlex"}]
    bridge = [{"title": "公正世界信念：概念、测量、及研究热点", "doi": None, "authors": ["杜建政"],
               "year": "2007", "source": "知网"}]
    merged, added = litbridge.merge_results(api, bridge)
    assert added == 0                                     # 同题去重
    assert len(merged) == 1


def test_merge_adds_new():
    api = [{"title": "A", "doi": None, "authors": [], "year": "2020", "source": "OpenAlex"}]
    bridge = [{"title": "B 全新中文文献", "doi": None, "authors": [], "year": "2021", "source": "知网"}]
    merged, added = litbridge.merge_results(api, bridge)
    assert added == 1 and len(merged) == 2


# ---- 抽取 JS 自测:语法合法(真实 DOM 匹配只能真机验证)-------------------------

def test_extract_js_syntax_valid_all_dbs():
    """生成的抽取 JS 在每个库画像上都语法合法(node --check)。无 node 则跳过。"""
    import shutil
    import subprocess
    import tempfile
    if not shutil.which("node"):
        import pytest
        pytest.skip("需要 node 校验 JS 语法")
    for db in ("cnki", "wanfang", "vip"):
        js = litbridge._extract_js(db)
        assert "querySelectorAll" in js and js.strip().endswith(")")
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write(js)
            path = fh.name
        try:
            r = subprocess.run(["node", "--check", path],
                               capture_output=True, text=True, timeout=15)
            assert r.returncode == 0, f"{db} 抽取 JS 语法非法:{r.stderr}"
        finally:
            import os
            os.unlink(path)


# ---- lit_cli 集成(mock 检索 + mock 桥) --------------------------------------

def _fake_search(query, sources=None, limit=10, year_from=None):
    return {"query": query, "per_source": {"openalex": 1}, "n_raw": 1,
            "n_deduped": 1, "n_duplicates": 0,
            "results": [{"title": "英文命中", "doi": "10.1/x", "authors": ["A"],
                         "year": "2020", "source": "OpenAlex", "oa_status": "gold",
                         "oa_url": None, "abstract": "", "pmid": None,
                         "pmcid": None, "arxiv_id": None}]}


def test_lit_cli_auto_bridges_and_merges(tmp_path, monkeypatch, capsys):
    from psyclaw.psych import litsearch, lit_cli as lc
    monkeypatch.setattr(litsearch, "search", _fake_search)
    monkeypatch.setattr(litbridge, "bridge_available", lambda **k: (True, ""))
    monkeypatch.setattr(litbridge, "bridge_search",
                        lambda q, **k: {"ok": True, "reason": "", "db": "cnki", "name": "知网",
                                        "records": [{"title": "知网独有中文文献", "doi": None,
                                                     "authors": ["杜建政"], "year": "2007",
                                                     "source": "知网", "oa_status": "unknown",
                                                     "oa_url": None, "abstract": "", "pmid": None,
                                                     "pmcid": None, "arxiv_id": None}]})
    rc = lc.lit_cli("公正世界信念", project_dir=str(tmp_path), limit=10)
    assert rc == 0
    out = capsys.readouterr().out
    assert "知网" in out and "新增 1" in out
    # 桥题录进了缓存
    import json
    cache = json.loads((tmp_path / "notes" / "lit_search.json").read_text(encoding="utf-8"))
    titles = [r["title"] for r in cache["results"]]
    assert "知网独有中文文献" in titles


def test_lit_cli_no_bridge_flag_skips(tmp_path, monkeypatch, capsys):
    from psyclaw.psych import litsearch, lit_cli as lc
    monkeypatch.setattr(litsearch, "search", _fake_search)
    called = {"bridged": False}
    monkeypatch.setattr(litbridge, "bridge_available",
                        lambda **k: called.__setitem__("bridged", True) or (True, ""))
    rc = lc.lit_cli("公正世界信念", project_dir=str(tmp_path), limit=10, bridge=False)
    assert rc == 0
    assert called["bridged"] is False                    # 没探测桥,直接跳过
