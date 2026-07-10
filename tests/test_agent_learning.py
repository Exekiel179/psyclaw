"""feat-065 —— 错误自学习 + 图片内联渲染接入 agent 模式(toolloop)。

- 循环内:失败工具结果蒸馏环境教训 → 当轮回灌给模型止损 + 返回 lessons 给调用方;
- ok=True 的输出**不**蒸馏(可能是 read_file 读到的日志/源码,报错字样是内容不是本机事实);
- REPL/CLI 侧:render_images_in_text 把文本里提到的图片内联渲染(共用)。
"""

from __future__ import annotations

from psyclaw import repl, toolloop as TL


class CapturingProvider:
    """逐轮弹脚本回复,并记录每次收到的 messages(供断言回灌内容)。"""
    name = "fake"

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen: list[list] = []

    def chat(self, messages, system=""):
        self.seen.append([dict(m) for m in messages])
        r = self.replies.pop(0) if self.replies else "最终答案"
        return iter([r])


def _boom_tools():
    def boom(a):
        raise RuntimeError("ModuleNotFoundError: No module named 'mne'")

    def ok_with_error_text(a):
        return "python: command not found"   # 正常返回的内容,不是本机失败

    return {
        "boom": {"desc": "炸", "args": "x", "run": boom, "side_effect": False},
        "cat_log": {"desc": "读日志", "args": "", "run": ok_with_error_text,
                    "side_effect": False},
    }


def _call(name, args="{}"):
    return f'```tool\n{{"name": "{name}", "args": {args}}}\n```'


# -- 循环内蒸馏 ---------------------------------------------------------------
def test_loop_collects_lessons_from_failed_tool():
    p = CapturingProvider([_call("boom"), "装不上,换环境跑。"])
    res = TL.run_tool_loop(p, "sys", [{"role": "user", "content": "跑分析"}],
                           tools=_boom_tools())
    assert res["stopped"] == "answered"
    assert len(res["lessons"]) == 1
    assert res["lessons"][0]["trigger"] == "mne"
    assert res["lessons"][0]["kind"] == "module"


def test_loop_feeds_lessons_back_to_model():
    p = CapturingProvider([_call("boom"), "好"])
    TL.run_tool_loop(p, "sys", [{"role": "user", "content": "跑"}],
                     tools=_boom_tools())
    feedback = p.seen[1][-1]["content"]          # 第二轮模型看到的工具结果回灌
    assert "环境教训" in feedback
    assert "mne" in feedback


def test_loop_no_lessons_from_ok_output_with_error_text():
    """read_file/日志类工具返回的报错字样是内容,不是本机事实——不学。"""
    p = CapturingProvider([_call("cat_log"), "好"])
    res = TL.run_tool_loop(p, "sys", [{"role": "user", "content": "看日志"}],
                           tools=_boom_tools())
    assert res["lessons"] == []


def test_loop_lessons_dedup_across_iters():
    p = CapturingProvider([_call("boom", '{"x": 1}'), _call("boom", '{"x": 2}'), "放弃"])
    res = TL.run_tool_loop(p, "sys", [{"role": "user", "content": "跑"}],
                           tools=_boom_tools())
    assert len(res["lessons"]) == 1              # 同一教训跨轮只记一次


def test_loop_answered_without_tools_has_empty_lessons():
    p = CapturingProvider(["直接回答"])
    res = TL.run_tool_loop(p, "sys", [{"role": "user", "content": "问"}],
                           tools=_boom_tools())
    assert res["stopped"] == "answered" and res["lessons"] == []


def test_collect_env_lessons_respects_seen_keys():
    results = [{"name": "b", "ok": False, "output": "No module named 'mne'"}]
    seen: set = set()
    assert len(TL.collect_env_lessons(results, seen)) == 1
    assert TL.collect_env_lessons(results, seen) == []   # 第二次同键不再出


# -- REPL 侧并入会话记忆 -------------------------------------------------------
def test_ingest_lessons_dedups_and_drafts(monkeypatch, capsys):
    from psyclaw import memory
    drafted = []
    monkeypatch.setattr(memory, "draft_lesson",
                        lambda t, l, source, kind=None: drafted.append((t, source, kind)))
    s = repl.ReplSession.__new__(repl.ReplSession)
    s.session_lessons = []
    s._session_lesson_keys = set()
    les = {"trigger": "mne", "lesson": "缺 mne", "kind": "module"}
    s._ingest_lessons([les])
    s._ingest_lessons([les])                     # agent 多次运行同教训不重复
    assert len(s.session_lessons) == 1
    assert drafted == [("mne", "error", "module")]
    assert "记下环境教训" in capsys.readouterr().out


# -- 图片内联渲染(REPL/CLI 共用)-----------------------------------------------
def test_render_images_in_text_renders_existing(tmp_path, capsys):
    img = tmp_path / "forest_plot.png"
    img.write_bytes(b"\x89PNG fake")
    n = repl.render_images_in_text(f"图已保存:{img}", force="iterm2")
    out = capsys.readouterr().out
    assert n == 1
    assert "forest_plot.png" in out
    assert "\033]1337;" in out                   # iTerm2 内联转义确已输出


def test_render_images_in_text_none_protocol(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"x")
    assert repl.render_images_in_text(str(img), force="none") == 0


def test_render_images_in_text_missing_file_skipped():
    assert repl.render_images_in_text("看 /no/such/plot.png", force="iterm2") == 0


def test_render_images_in_text_limit(tmp_path, capsys):
    paths = []
    for i in range(5):
        p = tmp_path / f"p{i}.png"
        p.write_bytes(b"x")
        paths.append(str(p))
    n = repl.render_images_in_text("\n".join(paths), force="iterm2", limit=3)
    assert n == 3
