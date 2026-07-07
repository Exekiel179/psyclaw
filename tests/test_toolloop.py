"""纯工具层循环测试 —— parse(纯)+ build/catalog + run_tool_loop(fake provider 离线)。"""

from __future__ import annotations

from psyclaw import toolloop as TL


class FakeProvider:
    """按脚本逐轮返回回复(每次 chat 弹一条);模拟模型的工具调用与最终答案。"""
    name = "fake"

    def __init__(self, replies):
        self.replies = list(replies)
        self.chats = 0

    def chat(self, messages, system=""):
        self.chats += 1
        r = self.replies.pop(0) if self.replies else "最终答案"
        return iter([r])


def _tools():
    state = {"writes": 0}

    def echo(a):
        return f"echoed {a.get('x')}"

    def writer(a):
        state["writes"] += 1
        return "wrote"

    tools = {
        "echo": {"desc": "回声", "args": "x", "run": echo, "side_effect": False},
        "writer": {"desc": "写", "args": "x", "run": writer, "side_effect": True},
    }
    return tools, state


# --- parse_tool_calls ---------------------------------------------------------

def test_parse_single():
    r = '前言\n```tool\n{"name": "search", "args": {"query": "焦虑"}}\n```\n后语'
    calls = TL.parse_tool_calls(r)
    assert calls == [{"name": "search", "args": {"query": "焦虑"}}]


def test_parse_multiple():
    r = ('```tool\n{"name":"a","args":{}}\n```\n'
         '```tool\n{"name":"b","args":{"k":1}}\n```')
    names = [c["name"] for c in TL.parse_tool_calls(r)]
    assert names == ["a", "b"]


def test_parse_none():
    assert TL.parse_tool_calls("没有工具调用的普通回复") == []


def test_parse_malformed_json():
    calls = TL.parse_tool_calls("```tool\n{not json}\n```")
    assert calls[0]["name"] is None and "JSON" in calls[0]["error"]


def test_parse_missing_name():
    calls = TL.parse_tool_calls('```tool\n{"args": {}}\n```')
    assert calls[0]["name"] is None and "name" in calls[0]["error"]


# --- 参数规范化与校验(v0.6 feat-043) ------------------------------------------

def test_normalize_args_dict_passthrough():
    assert TL._normalize_args({"q": 1}) == ({"q": 1}, None)
    assert TL._normalize_args(None) == ({}, None)


def test_normalize_args_json_string_parsed():
    args, err = TL._normalize_args('{"query": "x"}')   # 双重编码,模型常见
    assert args == {"query": "x"} and err is None
    assert TL._normalize_args("  ") == ({}, None)       # 空串→{}


def test_normalize_args_non_object_rejected():
    for bad in ([1, 2], 42, True, "not json", '"a string"', "[1,2]"):
        args, err = TL._normalize_args(bad)
        assert args == {} and err and "对象" in err, bad


def test_parse_coerces_json_string_args():
    calls = TL.parse_tool_calls('```tool\n{"name":"search","args":"{\\"q\\":1}"}\n```')
    assert calls == [{"name": "search", "args": {"q": 1}}]


def test_parse_rejects_list_args_with_guiding_error():
    calls = TL.parse_tool_calls('```tool\n{"name":"search","args":[1,2]}\n```')
    assert calls[0]["name"] == "search" and calls[0]["args"] == {}
    assert "对象" in calls[0]["error"]


def test_parse_rejects_non_string_name():
    calls = TL.parse_tool_calls('```tool\n{"name":123,"args":{}}\n```')
    assert calls[0]["name"] is None and "字符串" in calls[0]["error"]


def test_exec_bad_args_reported_as_failure_not_success():
    """畸形 args 经 parse 拦截 → 执行层标 ok=False,不再崩工具、不再误标成功。"""
    tools = {"echo": {"desc": "e", "args": "x",
                      "run": lambda a: a.get("x"), "side_effect": False}}
    calls = TL.parse_tool_calls('```tool\n{"name":"echo","args":[1,2]}\n```')
    r = TL._exec_tool(calls[0], tools, None, None)
    assert r["ok"] is False and "对象" in r["output"]


def test_exec_tool_exception_marked_failure():
    tools = {"boom": {"desc": "b", "args": "",
                      "run": lambda a: 1 / 0, "side_effect": False}}
    r = TL._exec_tool({"name": "boom", "args": {}}, tools, None, None)
    assert r["ok"] is False and "异常" in r["output"]


# --- 无进展检测(v0.6 feat-044) ------------------------------------------------

def test_calls_signature_stable_and_order_insensitive():
    a = [{"name": "s", "args": {"q": 1, "z": 2}}]
    b = [{"name": "s", "args": {"z": 2, "q": 1}}]     # 键序不同 → 同签名
    assert TL._calls_signature(a) == TL._calls_signature(b)
    c = [{"name": "s", "args": {"q": 9}}]
    assert TL._calls_signature(a) != TL._calls_signature(c)


def test_empty_reply_nudged_then_answers():
    prov = FakeProvider(["", "  ", "真正的答案"])       # 两次空 → 追问 → 答案
    tools, _ = _tools()
    res = TL.run_tool_loop(prov, "s", [{"role": "user", "content": "q"}], tools=tools)
    assert res["stopped"] == "answered" and res["final"] == "真正的答案"
    assert prov.chats == 3


def test_empty_reply_streak_stops_no_progress():
    prov = FakeProvider([""] * 10)
    tools, _ = _tools()
    res = TL.run_tool_loop(prov, "s", [{"role": "user", "content": "q"}], tools=tools)
    assert res["stopped"] == "no_progress"
    assert prov.chats == TL._MAX_NOPROGRESS + 1


def test_repeated_identical_call_stops_no_progress():
    prov = FakeProvider(['```tool\n{"name":"echo","args":{"x":1}}\n```'] * 10)
    tools, _ = _tools()
    res = TL.run_tool_loop(prov, "s", [{"role": "user", "content": "q"}], tools=tools)
    assert res["stopped"] == "no_progress"
    # 相同调用执行 _MAX_NOPROGRESS 次后,第 +1 次识别为卡住并停(不空转到 max_iters)
    assert len(res["trace"]) == TL._MAX_NOPROGRESS
    assert prov.chats == TL._MAX_NOPROGRESS + 1


def test_varied_calls_do_not_trigger_no_progress():
    prov = FakeProvider(['```tool\n{"name":"echo","args":{"x":1}}\n```',
                         '```tool\n{"name":"echo","args":{"x":2}}\n```',
                         '```tool\n{"name":"echo","args":{"x":3}}\n```',
                         "答案"])
    tools, _ = _tools()
    res = TL.run_tool_loop(prov, "s", [{"role": "user", "content": "q"}], tools=tools)
    assert res["stopped"] == "answered" and len(res["trace"]) == 3


def test_non_empty_answer_still_returns_immediately():
    prov = FakeProvider(["这就是最终答案"])
    tools, _ = _tools()
    res = TL.run_tool_loop(prov, "s", [{"role": "user", "content": "q"}], tools=tools)
    assert res["stopped"] == "answered" and res["iters"] == 1


# --- build_tools / catalog ----------------------------------------------------

def test_build_tools_shape():
    tools = TL.build_tools(".")
    assert {"search", "read_file", "save_file", "kg_query", "recall"} <= set(tools)
    assert tools["save_file"]["side_effect"] is True
    assert tools["search"]["side_effect"] is False


def test_catalog_lists_tools():
    cat = TL.render_tool_catalog(TL.build_tools("."))
    assert "```tool" in cat and "save_file" in cat and "[副作用" in cat


# --- run_tool_loop ------------------------------------------------------------

def test_loop_calls_tool_then_answers():
    prov = FakeProvider(['```tool\n{"name":"echo","args":{"x":1}}\n```', "最终答案"])
    tools, _ = _tools()
    res = TL.run_tool_loop(prov, "sys", [{"role": "user", "content": "q"}], tools=tools)
    assert res["stopped"] == "answered"
    assert res["final"] == "最终答案"
    assert res["iters"] == 2
    assert res["trace"][0]["output"] == "echoed 1"


def test_loop_max_iters():
    # 各轮参数不同(否则会先触发 feat-044 无进展检测);验证 max_iters 硬顶
    prov = FakeProvider(['```tool\n{"name":"echo","args":{"x":%d}}\n```' % i
                         for i in range(10)])
    tools, _ = _tools()
    res = TL.run_tool_loop(prov, "s", [{"role": "user", "content": "q"}],
                           tools=tools, max_iters=3)
    assert res["stopped"] == "max_iters" and res["iters"] == 3


def test_side_effect_denied_without_approval():
    prov = FakeProvider(['```tool\n{"name":"writer","args":{}}\n```', "done"])
    tools, state = _tools()
    res = TL.run_tool_loop(prov, "s", [{"role": "user", "content": "q"}],
                           tools=tools, approve=lambda c: False)
    assert "未批准" in res["trace"][0]["output"]
    assert state["writes"] == 0


def test_side_effect_runs_with_approval():
    prov = FakeProvider(['```tool\n{"name":"writer","args":{}}\n```', "done"])
    tools, state = _tools()
    TL.run_tool_loop(prov, "s", [{"role": "user", "content": "q"}],
                     tools=tools, approve=lambda c: True)
    assert state["writes"] == 1


def test_unknown_tool_reported():
    prov = FakeProvider(['```tool\n{"name":"nope","args":{}}\n```', "done"])
    tools, _ = _tools()
    res = TL.run_tool_loop(prov, "s", [{"role": "user", "content": "q"}], tools=tools)
    assert "未知工具" in res["trace"][0]["output"]


def test_emit_called_per_tool():
    prov = FakeProvider(['```tool\n{"name":"echo","args":{}}\n```', "done"])
    tools, _ = _tools()
    events = []
    TL.run_tool_loop(prov, "s", [{"role": "user", "content": "q"}],
                     tools=tools, emit=events.append)
    assert events and "echo" in events[0]


# --- 截断防护(修「工具调用中途提前停止」) --------------------------------------

def test_has_truncated_tool_block():
    assert TL.has_truncated_tool_block('```tool\n{"name":"echo"')            # 未闭合
    assert not TL.has_truncated_tool_block('```tool\n{"name":"e"}\n```')     # 完整
    assert not TL.has_truncated_tool_block("普通回复没有块")
    assert not TL.has_truncated_tool_block("")
    # 一个完整 + 一个截断 → 仍算截断
    assert TL.has_truncated_tool_block(
        '```tool\n{"name":"a","args":{}}\n```\n```tool\n{"name":"b"')


def test_loop_truncated_block_not_treated_as_answer():
    """截断的 tool 块不能被误判成最终答案——回灌续写提示后继续。"""
    prov = FakeProvider(['先说明\n```tool\n{"name":"echo","args":{"x":',  # 被截断
                         '```tool\n{"name":"echo","args":{"x":1}}\n```',   # 重发完整
                         "最终答案"])
    tools, _ = _tools()
    res = TL.run_tool_loop(prov, "s", [{"role": "user", "content": "q"}], tools=tools)
    assert res["stopped"] == "answered"
    assert res["final"] == "最终答案"
    assert res["trace"] and res["trace"][0]["output"] == "echoed 1"
    assert prov.chats == 3  # 截断轮 + 重发轮 + 答案轮


def test_loop_truncation_streak_gives_up():
    """连续截断超上限 → stopped=truncated,不无限循环、不静默。"""
    prov = FakeProvider(['```tool\n{"name":"echo"'] * 10)
    tools, _ = _tools()
    res = TL.run_tool_loop(prov, "s", [{"role": "user", "content": "q"}], tools=tools)
    assert res["stopped"] == "truncated"
    assert "截断" in res["final"]
    assert prov.chats == TL._MAX_TRUNC_STREAK + 1  # 首次 + 重试上限


def test_loop_stop_reason_max_tokens_triggers_retry():
    """无 tool 块但 provider 报 max_tokens 截断 → 续写而非当答案。"""

    class CutProvider(FakeProvider):
        def __init__(self, replies, reasons):
            super().__init__(replies)
            self.reasons = list(reasons)
            self.last_stop_reason = ""

        def chat(self, messages, system=""):
            self.last_stop_reason = self.reasons.pop(0) if self.reasons else ""
            return super().chat(messages, system)

    prov = CutProvider(["写到一半的普通文本被砍", "完整的最终答案"],
                       ["max_tokens", "end_turn"])
    tools, _ = _tools()
    res = TL.run_tool_loop(prov, "s", [{"role": "user", "content": "q"}], tools=tools)
    assert res["stopped"] == "answered"
    assert res["final"] == "完整的最终答案"


def test_loop_complete_call_plus_truncated_tail_executes_and_notes():
    """完整调用 + 尾部截断残块:执行完整的,回灌里告知残块未执行。"""
    convo_seen = []

    class SpyProvider(FakeProvider):
        def chat(self, messages, system=""):
            convo_seen.append([dict(m) for m in messages])
            return super().chat(messages, system)

    prov = SpyProvider(['```tool\n{"name":"echo","args":{"x":2}}\n```\n'
                        '```tool\n{"name":"echo"',            # 尾部残块
                        "最终答案"])
    tools, _ = _tools()
    res = TL.run_tool_loop(prov, "s", [{"role": "user", "content": "q"}], tools=tools)
    assert res["stopped"] == "answered"
    assert res["trace"][0]["output"] == "echoed 2"
    # 第二次 chat 的回灌消息应包含「截断残块未执行」提示
    feedback = convo_seen[1][-1]["content"]
    assert "截断" in feedback and "未被执行" in feedback


def test_loop_default_max_iters_raised():
    """默认迭代上限 ≥24:长研究任务不再 6 轮就停。"""
    import inspect
    sig = inspect.signature(TL.run_tool_loop)
    assert sig.parameters["max_iters"].default >= 24


# --- save_file 路径允许清单(v0.3 外审 MEDIUM) ----------------------------------

def test_save_path_allows_inside_project(tmp_path):
    assert TL.save_path_denied("notes/out.md", str(tmp_path)) is None
    assert TL.save_path_denied(str(tmp_path / "sub" / "a.txt"), str(tmp_path)) is None


def test_save_path_denies_relative_escape(tmp_path):
    d = TL.save_path_denied("../outside.txt", str(tmp_path))
    assert d and "项目根之外" in d


def test_save_path_denies_absolute_outside(tmp_path):
    d = TL.save_path_denied("/tmp/psyclaw_evil.txt", str(tmp_path))
    assert d and "项目根之外" in d


def test_save_path_denies_home_credentials(tmp_path):
    d = TL.save_path_denied("~/.ssh/authorized_keys", str(tmp_path))
    assert d  # 项目根之外(通常)或凭据类,任一理由拒即可


def test_save_path_denies_credential_names_inside_root(tmp_path):
    for bad in (".env", "id_rsa", "server.pem", "client.key"):
        d = TL.save_path_denied(bad, str(tmp_path))
        assert d and "凭据类" in d, bad


def test_save_path_denies_credential_dir_inside_root(tmp_path):
    d = TL.save_path_denied(".ssh/config", str(tmp_path))
    assert d and "凭据类" in d


def test_save_path_denies_symlink_target(tmp_path):
    real = tmp_path / "real.txt"
    real.write_text("x", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(real)
    d = TL.save_path_denied(str(link), str(tmp_path))
    assert d and "软链接" in d


def test_save_path_denies_symlink_dir_escape(tmp_path):
    """途径软链目录逃逸:resolve 消解后落到根外 → 拒。"""
    outside = tmp_path.parent / "psyclaw_outside_probe"
    outside.mkdir(exist_ok=True)
    ln = tmp_path / "esc"
    ln.symlink_to(outside, target_is_directory=True)
    d = TL.save_path_denied("esc/x.txt", str(tmp_path))
    assert d and "项目根之外" in d


def test_save_path_denies_empty():
    assert TL.save_path_denied("", ".") is not None


def test_save_tool_rejects_escape_without_writing(tmp_path):
    """端到端:save_file 工具对逃逸路径直接拒,不落盘。"""
    tools = TL.build_tools(str(tmp_path))
    out = tools["save_file"]["run"]({"path": "../evil.md", "content": "x"})
    assert "拒绝写入" in out
    assert not (tmp_path.parent / "evil.md").exists()


# --- 长会话上下文修剪(v0.3 feat-033) -------------------------------------------

def _result_msg(name: str, payload: str) -> dict:
    return {"role": "user",
            "content": f"# 工具结果\n\n## {name}\n{payload}\n\n据以上结果继续。"}


def test_compress_result_msg_keeps_tool_and_first_line():
    msg = ("# 工具结果\n\n## search\n命中 8 条结果\n第二行细节很长" + "x" * 500
           + "\n\n## read_file(失败)\n文件不存在\n\n据以上结果继续。")
    out = TL._compress_result_msg(msg)
    assert out.startswith(TL._COMPRESSED_HEAD)
    assert "## search" in out and "命中 8 条结果" in out
    assert "## read_file(失败)" in out and "文件不存在" in out
    assert "第二行细节" not in out          # 只保首行
    assert len(out) < len(msg)


def test_trim_convo_keeps_recent_full_compresses_old():
    base = [{"role": "user", "content": "任务"}]
    convo = list(base)
    for i in range(6):   # 6 轮结果
        convo.append({"role": "assistant", "content": f"```tool\n{{}}\n```{i}"})
        convo.append(_result_msg(f"t{i}", "详情" * 100))
    TL.trim_convo(convo, base_len=len(base))
    results = [m for m in convo if m["role"] == "user" and
               m["content"].startswith("# 工具结果")]
    compressed = [m for m in results if m["content"].startswith(TL._COMPRESSED_HEAD)]
    assert len(results) == 6 and len(compressed) == 3   # 旧 3 压缩,近 3 完整
    # 压缩的是最早的 t0..t2
    assert all(f"## t{i}" in compressed[i]["content"] for i in range(3))
    # 原始历史(base)与 assistant 消息未动
    assert convo[0]["content"] == "任务"
    assert all(m["content"].startswith("```tool") for m in convo if m["role"] == "assistant")


def test_trim_convo_idempotent_and_under_threshold_untouched():
    base_len = 0
    convo = [_result_msg(f"t{i}", "x" * 50) for i in range(3)]
    before = [m["content"] for m in convo]
    TL.trim_convo(convo, base_len)
    assert [m["content"] for m in convo] == before   # ≤3 条不动
    convo.append(_result_msg("t3", "y"))
    TL.trim_convo(convo, base_len)
    TL.trim_convo(convo, base_len)                   # 再跑一次不重复压缩
    compressed = [m for m in convo if m["content"].startswith(TL._COMPRESSED_HEAD)]
    assert len(compressed) == 1


def test_trim_convo_never_touches_caller_history():
    """base_len 之前即便长得像工具结果也不动(调用方 REPL 历史)。"""
    convo = [_result_msg("history", "旧会话里的工具结果" * 50)]
    keep = convo[0]["content"]
    for i in range(5):
        convo.append(_result_msg(f"t{i}", "z" * 200))
    TL.trim_convo(convo, base_len=1)
    assert convo[0]["content"] == keep


def test_loop_trims_old_results_end_to_end():
    """跑满多轮后,早期工具结果在 convo 里被压缩(经 SpyProvider 观察)。"""
    convo_lens = []

    class SpyProvider(FakeProvider):
        def chat(self, messages, system=""):
            convo_lens.append(sum(len(m["content"]) for m in messages))
            heads = [m["content"].splitlines()[0] for m in messages
                     if m["role"] == "user" and m["content"].startswith("# 工具结果")]
            spy_heads.append(heads)
            return super().chat(messages, system)

    spy_heads: list = []
    prov = SpyProvider(['```tool\n{"name":"echo","args":{"x":%d}}\n```' % i
                        for i in range(6)] + ["最终答案"])
    tools, _ = _tools()
    res = TL.run_tool_loop(prov, "s", [{"role": "user", "content": "q"}], tools=tools)
    assert res["stopped"] == "answered"
    # 最后一次 chat 时:6 条结果中应有 3 条已压缩
    last = spy_heads[-1]
    assert len(last) == 6
    assert sum(1 for h in last if h.startswith(TL._COMPRESSED_HEAD)) == 3
def _fake_res(final="答案", stopped="answered", iters=2, tools=("echo", "search")):
    return {"final": final, "iters": iters, "stopped": stopped,
            "trace": [{"name": t, "ok": True, "output": "x"} for t in tools]}
def test_log_and_read_agent_runs(tmp_path):
    TL.log_agent_run(str(tmp_path), "第一个任务", _fake_res())
    TL.log_agent_run(str(tmp_path), "第二个任务", _fake_res(stopped="max_iters"))
    runs = TL.read_agent_runs(str(tmp_path))
    assert len(runs) == 2
    assert runs[0]["task"] == "第二个任务"          # 新→旧
    assert runs[0]["stopped"] == "max_iters"
    assert runs[1]["tools"] == ["echo", "search"]
    assert runs[1]["ts"]                            # 有时间戳
def test_read_agent_runs_limit_and_missing(tmp_path):
    assert TL.read_agent_runs(str(tmp_path)) == []   # 文件缺失 → []
    for i in range(5):
        TL.log_agent_run(str(tmp_path), f"t{i}", _fake_res())
    assert len(TL.read_agent_runs(str(tmp_path), limit=3)) == 3
def test_read_agent_runs_skips_bad_lines(tmp_path):
    TL.log_agent_run(str(tmp_path), "good", _fake_res())
    p = tmp_path / ".psyclaw" / "agent_runs.jsonl"
    p.write_text(p.read_text(encoding="utf-8") + "{broken json\n", encoding="utf-8")
    runs = TL.read_agent_runs(str(tmp_path))
    assert len(runs) == 1 and runs[0]["task"] == "good"
def test_log_agent_run_truncates_heads(tmp_path):
    TL.log_agent_run(str(tmp_path), "长" * 500, _fake_res(final="答" * 500))
    r = TL.read_agent_runs(str(tmp_path))[0]
    assert len(r["task"]) == TL._RUNS_MAX_HEAD
    assert len(r["final_head"]) == TL._RUNS_MAX_HEAD
def test_sanitize_drops_empty_content():
    msgs = [{"role": "user", "content": "hi"},
            {"role": "assistant", "content": "  "},
            {"role": "user", "content": "again"}]
    out = TL.sanitize_messages(msgs)
    assert out == [{"role": "user", "content": "hi\n\nagain"}]
def test_sanitize_merges_consecutive_same_role():
    msgs = [{"role": "user", "content": "a"},
            {"role": "user", "content": "b"},
            {"role": "assistant", "content": "c"}]
    out = TL.sanitize_messages(msgs)
    assert out == [{"role": "user", "content": "a\n\nb"},
                   {"role": "assistant", "content": "c"}]
def test_sanitize_first_must_be_user():
    msgs = [{"role": "assistant", "content": "x"},
            {"role": "user", "content": "y"}]
    out = TL.sanitize_messages(msgs)
    assert out[0]["role"] == "user"
def test_sanitize_drops_unknown_roles():
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    out = TL.sanitize_messages(msgs)
    assert out == [{"role": "user", "content": "u"}]
def test_sanitize_non_string_content_coerced_or_dropped():
    msgs = [{"role": "user", "content": None}, {"role": "user", "content": "ok"}]
    assert TL.sanitize_messages(msgs) == [{"role": "user", "content": "ok"}]
def test_loop_sends_only_sanitized_messages_to_provider():
    """回灌进行中,provider 每次收到的消息都合法:非空 content + 角色交替 + 首条 user。"""
    seen = []
    class SpyProvider(FakeProvider):
        def chat(self, messages, system=""):
            seen.append([dict(m) for m in messages])
            return super().chat(messages, system)
    prov = SpyProvider(['```tool\n{"name":"echo","args":{"x":1}}\n```', "答案"])
    tools, _ = _tools()
    TL.run_tool_loop(prov, "s", [{"role": "user", "content": "q"}], tools=tools)
    for msgs in seen:
        assert msgs, "不应发空消息列表"
        assert msgs[0]["role"] == "user"
        assert all(str(m["content"]).strip() for m in msgs)   # 无空 content
        roles = [m["role"] for m in msgs]
        assert all(roles[i] != roles[i + 1] for i in range(len(roles) - 1))  # 交替
