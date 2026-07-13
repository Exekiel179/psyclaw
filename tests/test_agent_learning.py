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
def test_render_images_in_text_renders_existing(tmp_path, capsys, monkeypatch):
    import sys as _sys
    monkeypatch.setattr(_sys.stdout, "isatty", lambda: True, raising=False)
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


def test_render_images_in_text_limit(tmp_path, capsys, monkeypatch):
    import sys as _sys
    monkeypatch.setattr(_sys.stdout, "isatty", lambda: True, raising=False)
    paths = []
    for i in range(5):
        p = tmp_path / f"p{i}.png"
        p.write_bytes(b"x")
        paths.append(str(p))
    n = repl.render_images_in_text("\n".join(paths), force="iterm2", limit=3)
    assert n == 3
def _img_sess(proto="iterm2"):
    s = repl.ReplSession.__new__(repl.ReplSession)
    s.conf = {"image_protocol": proto}
    return s
def test_expand_at_image_renders_and_injects_meta(tmp_path, capsys, monkeypatch):
    import sys as _sys
    monkeypatch.setattr(_sys.stdout, "isatty", lambda: True, raising=False)
    img = tmp_path / "erp_wave.png"
    img.write_bytes(b"\x89PNG fake data")
    s = _img_sess()
    out = s._expand_files(f"帮我看看 @{img} 这张图")
    printed = capsys.readouterr().out
    assert "\033]1337;" in printed                 # 内联转义已输出给用户
    assert "引用了图片" in out                      # 模型收到元信息……
    assert "PNG fake" not in out                   # ……而不是二进制内容
    assert "帮我看看" in out and "这张图" in out    # 其余文本原样保留
def test_expand_at_image_unsupported_terminal_notes(tmp_path, capsys):
    img = tmp_path / "plot.png"
    img.write_bytes(b"x")
    s = _img_sess(proto="none")
    out = s._expand_files(f"@{img}")
    assert "不支持内联显示" in out
    assert "不支持内联" in capsys.readouterr().out
def test_expand_at_text_file_still_excerpts(tmp_path, capsys):
    f = tmp_path / "notes.md"
    f.write_text("# 假设\nH1: 正念降低焦虑\n", encoding="utf-8")
    s = _img_sess()
    out = s._expand_files(f"@{f}")
    assert "正念降低焦虑" in out                    # 文本文件行为不回归
class TestRenderImageDirect:
    """feat-086(评审修复):@图片 直接渲染已知路径,不回环正则;force 不越 TTY。"""
    def _fake_env(self, monkeypatch, tmp_path, name):
        from pathlib import Path

        from psyclaw import imgview
        img = tmp_path / name
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 40)
        monkeypatch.setattr(imgview, "supports_inline", lambda force=None: "iterm2")
        monkeypatch.setattr(imgview, "render_escape",
                            lambda p, force=None: "<ESC:" + str(p).rsplit("/", 1)[-1] + ">")
        return img
    def test_parenthesized_filename_renders(self, monkeypatch, tmp_path, capsys):
        """fig(1).png:正则匹配不到的文件名,直接渲染路径照样出图。"""
        from psyclaw.repl import render_image_file
        img = self._fake_env(monkeypatch, tmp_path, "fig(1).png")
        assert render_image_file(img) is True
        assert "fig(1).png" in capsys.readouterr().out
    def test_plus_and_percent_filename_renders(self, monkeypatch, tmp_path, capsys):
        from psyclaw.repl import render_image_file
        img = self._fake_env(monkeypatch, tmp_path, "fig+2%20a.png")
        assert render_image_file(img) is True
    def test_forced_protocol_does_not_write_to_pipe(self, monkeypatch):
        """feat-086:isatty 先于 force——配置了 image_protocol 的用户重定向
        stdout 时不再被灌 base64 转义(此前 force 越过 TTY 检查)。"""
        import io
        import sys as _sys
        from psyclaw import imgview
        fake = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")  # 非 TTY
        monkeypatch.setattr(_sys, "stdout", fake)
        assert imgview.supports_inline("iterm2") is None
        assert imgview.supports_inline("kitty") is None
        assert imgview.supports_inline("none") is None
    def test_forced_protocol_honored_on_tty(self, monkeypatch):
        import sys as _sys
        from psyclaw import imgview
        class _Tty:
            def isatty(self):
                return True
        monkeypatch.setattr(_sys, "stdout", _Tty())
        assert imgview.supports_inline("iterm2") == "iterm2"
        assert imgview.supports_inline("none") is None
class TestDraftLessonsBatch:
    """feat-087(评审修复):批量落卡单卡失败不中断,CLI 按实际落卡数如实报。"""
    def test_returns_actual_saved_count(self, monkeypatch):
        from psyclaw import memory as M
        calls = {"n": 0}
        def flaky(trigger, lesson, source, kind=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("记忆库不可写")
        monkeypatch.setattr(M, "draft_lesson", flaky)
        lessons = [{"trigger": "a", "lesson": "坑A"},
                   {"trigger": "b", "lesson": "坑B"},
                   {"trigger": "c", "lesson": "坑C"}]
        assert M.draft_lessons(lessons) == 2       # 首卡失败,后两张仍落
        assert calls["n"] == 3                     # 不 break,逐张尝试
    def test_all_fail_returns_zero(self, monkeypatch):
        from psyclaw import memory as M
        monkeypatch.setattr(M, "draft_lesson",
                            lambda *a, **k: (_ for _ in ()).throw(OSError()))
        assert M.draft_lessons([{"trigger": "a", "lesson": "x"}]) == 0
    def test_cmd_agent_reports_honest_count(self, monkeypatch, capsys):
        """落卡全失败时 CLI 明说「未持久化」,不再谎报 N 条已落卡。"""
        from psyclaw import cli
        from psyclaw import memory as M
        monkeypatch.setattr(M, "draft_lesson",
                            lambda *a, **k: (_ for _ in ()).throw(OSError()))
        monkeypatch.setattr(cli.cfg, "load_config", lambda: {"provider": "mock"})
        fake_res = {"final": "done", "iters": 1, "stopped": "answered",
                    "trace": [], "lessons": [{"trigger": "t", "lesson": "坑"}]}
        import psyclaw.toolloop as TL2
        monkeypatch.setattr(TL2, "run_tool_loop",
                            lambda *a, **k: fake_res)
        monkeypatch.setattr(TL2, "log_agent_run", lambda *a, **k: None)
        import argparse
        ns = argparse.Namespace(task=["测试"], auto=False, max_iters=4,
                                history=None)
        rc = cli.cmd_agent(ns)
        out = capsys.readouterr().out
        assert rc == 0
        assert "落卡全部失败" in out and "未持久化" in out
