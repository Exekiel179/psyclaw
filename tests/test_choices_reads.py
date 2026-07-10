"""键盘选择器(choices)+ 自动读文件(read 块/权限模式)测试。"""

from __future__ import annotations

from psyclaw import choices as C
from psyclaw.choices import (format_free_answer, format_selection_message,
                            parse_choices, resolve_selection)
from psyclaw.repl import gather_read_results, parse_read_requests


# --- parse_choices ------------------------------------------------------------

def test_parse_choices_block():
    r = ('请选择:\n```choices\n'
         '{"question": "复现哪些实验?", "multi": true, '
         '"options": ["研究1a", "研究1b", "研究2a"]}\n```')
    c = parse_choices(r)
    assert c["question"] == "复现哪些实验?"
    assert c["multi"] is True and len(c["options"]) == 3


def test_parse_choices_checkbox_heuristic():
    # 用户实测的真实格式:• [ ] 前缀复选清单
    r = ("请选择你要复现的实验(可多选):\n\n"
         "• [ ] 研究1a:单一债务方案框架效应(被试间设计)\n"
         "• [ ] 研究1b:单一债务方案框架效应(被试内设计)\n"
         "• [ ] 研究2a:配对债务方案框架效应(被试间设计)\n")
    c = parse_choices(r)
    assert c is not None and len(c["options"]) == 3
    assert c["options"][0].startswith("研究1a")
    assert "可多选" in c["question"]
    assert c["multi"] is True


def test_parse_choices_dash_checkbox_and_min_two():
    assert parse_choices("- [ ] 只有一项") is None            # <2 项不触发
    c = parse_choices("选项:\n- [ ] A\n- [ ] B")
    assert c and c["options"] == ["A", "B"]


def test_parse_choices_none_and_bad_block():
    assert parse_choices("普通回复,没有选项。") is None
    # 块坏了 → 回落启发式(此处也无清单)→ None
    assert parse_choices("```choices\n{bad json}\n```") is None


# --- resolve_selection ---------------------------------------------------------

def test_resolve_numbers_all_cancel_text():
    opts = ["A", "B", "C"]
    assert resolve_selection("1,3", opts) == ["A", "C"]
    assert resolve_selection("2 3", opts) == ["B", "C"]
    assert resolve_selection("全部", opts) == ["A", "B", "C"]
    assert resolve_selection("", opts) == []
    assert resolve_selection("B", opts) == ["B"]
    assert resolve_selection("9", opts) == []                 # 越界忽略


def test_resolve_single_select():
    assert resolve_selection("1,2", ["A", "B"], multi=False) == ["A"]
    assert resolve_selection("all", ["A", "B"], multi=False) == ["A"]


def test_format_selection_message():
    msg = format_selection_message(["研究1a", "研究2a"], "复现哪些实验?")
    assert "研究1a、研究2a" in msg and "复现哪些实验?" in msg


def test_format_free_answer():
    assert format_free_answer("y", "用哪个数据集?") == "(针对「用哪个数据集?」)y"
    assert format_free_answer("随便", "请选择") == "随便"     # 默认问题不加前缀


# --- _pick_numbered:非空非编号输入当自由文本回传,别吞掉(用户实测:打 y 消失)---------
def _choice(multi=False):
    return {"question": "用哪个数据集?", "multi": multi, "options": ["sample", "eegbci"]}


def test_pick_numbered_valid_number(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "2")
    chosen, free = C._pick_numbered(_choice())
    assert chosen == ["eegbci"] and free is None


def test_pick_numbered_free_text_not_dropped(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "y")
    chosen, free = C._pick_numbered(_choice())
    assert chosen == [] and free == "y"             # y 不是编号 → 作为自由文本回传


def test_pick_numbered_empty_is_skip(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "")
    chosen, free = C._pick_numbered(_choice())
    assert chosen == [] and free is None            # 回车 = 跳过


def test_pick_numbered_eof_is_skip(monkeypatch):
    def _eof(*_a, **_k):
        raise EOFError
    monkeypatch.setattr("builtins.input", _eof)
    assert C._pick_numbered(_choice()) == ([], None)


# --- read 块 -------------------------------------------------------------------

def test_parse_read_requests():
    r = "我来读取。\n```read\nF:\\data\\a.csv\n\"b.md\"\n```\n另外\n```read\na.csv\n```"
    assert parse_read_requests(r) == ["F:\\data\\a.csv", "b.md", "a.csv"]
    assert parse_read_requests("无读取请求") == []


def test_gather_reads_file_and_missing(tmp_path):
    f = tmp_path / "scores.csv"
    f.write_text("group,y\na,1\nb,2\n", encoding="utf-8")
    msg, notes = gather_read_results([str(f), str(tmp_path / "nope.csv")])
    assert "自动读取结果" in msg and "group" in msg
    assert "[文件不存在" in msg
    assert any("已自动读取" in n for n in notes)


def test_gather_refuses_data_raw(tmp_path):
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    f = raw / "p.csv"
    f.write_text("x\n1\n", encoding="utf-8")
    msg, notes = gather_read_results([str(f)])
    assert "拒绝读取" in msg and "受保护" in msg
    assert "x\n1" not in msg                                   # 内容绝不外泄


def test_gather_caps_files(tmp_path):
    files = []
    for i in range(6):
        p = tmp_path / f"f{i}.txt"
        p.write_text("hello", encoding="utf-8")
        files.append(str(p))
    msg, _ = gather_read_results(files, limit=4)
    assert "其余 2 个" in msg
def _feed(keys):
    it = iter(keys)
    return lambda: next(it)
def _single():
    return {"question": "选哪个?", "multi": False, "options": ["甲", "乙", "丙"]}
def _multi():
    return {"question": "要哪些?", "multi": True, "options": ["甲", "乙", "丙"]}
def test_inline_single_down_enter():
    from psyclaw.choices import _pick_inline
    chosen, free = _pick_inline(_single(), get_key=_feed(["DOWN", "ENTER"]))
    assert chosen == ["乙"] and free is None
def test_inline_single_digit_selects_immediately():
    from psyclaw.choices import _pick_inline
    chosen, free = _pick_inline(_single(), get_key=_feed(["3"]))
    assert chosen == ["丙"] and free is None
def test_inline_multi_space_toggle_enter():
    from psyclaw.choices import _pick_inline
    chosen, free = _pick_inline(
        _multi(), get_key=_feed([" ", "DOWN", "DOWN", " ", "ENTER"]))
    assert chosen == ["甲", "丙"] and free is None
def test_inline_multi_untoggle():
    from psyclaw.choices import _pick_inline
    chosen, _ = _pick_inline(_multi(), get_key=_feed([" ", " ", "DOWN", " ", "ENTER"]))
    assert chosen == ["乙"]                      # 甲勾了又取消
def test_inline_multi_enter_without_checks_takes_highlight():
    from psyclaw.choices import _pick_inline
    chosen, _ = _pick_inline(_multi(), get_key=_feed(["DOWN", "ENTER"]))
    assert chosen == ["乙"]
def test_inline_esc_skips():
    from psyclaw.choices import _pick_inline
    assert _pick_inline(_single(), get_key=_feed(["ESC"])) == ([], None)
def test_inline_up_wraps_around():
    from psyclaw.choices import _pick_inline
    chosen, _ = _pick_inline(_single(), get_key=_feed(["UP", "ENTER"]))
    assert chosen == ["丙"]                      # 首行向上回绕到末行
def test_inline_free_text_keeps_first_char():
    from psyclaw.choices import _pick_inline
    chosen, free = _pick_inline(
        _single(), get_key=_feed(["都"]), read_rest=lambda _="": "行你决定")
    assert chosen == [] and free == "都行你决定"   # 打字不吞,首字符保留(承 feat-060)
def test_inline_multi_digit_toggles():
    from psyclaw.choices import _pick_inline
    chosen, _ = _pick_inline(_multi(), get_key=_feed(["2", "ENTER"]))
    assert chosen == ["乙"]
def test_inline_no_altscreen_escapes(capsys):
    """回归:渲染绝不进备用屏/清屏(Windows 蓝色独立屏幕的根源已弃)。"""
    from psyclaw.choices import _pick_inline
    _pick_inline(_single(), get_key=_feed(["ENTER"]))
    out = capsys.readouterr().out
    assert "\x1b[?1049h" not in out and "\x1b[2J" not in out
    assert "选哪个?" in out and "1. 甲" in out
def test_inline_detail_zone_shows_full_text_when_truncated(monkeypatch, capsys):
    """feat-071:高亮项超宽被截断时,详情区给全文(用户反馈:看不见选项所说的方案)。"""
    import os
    import shutil
    from psyclaw.choices import _pick_inline
    monkeypatch.setattr(shutil, "get_terminal_size",
                        lambda fallback=None: os.terminal_size((60, 24)))
    long_opt = "方案B:" + "先做预注册再收数据," * 12
    choice = {"question": "选方案", "multi": False, "options": ["方案A:简版", long_opt]}
    chosen, _ = _pick_inline(choice, get_key=_feed(["DOWN", "ENTER"]))
    out = capsys.readouterr().out
    assert chosen == [long_opt]
    assert "…" in out                              # 菜单行截断了……
    assert "▏" in out                              # ……详情区补全文
    assert "先做预注册再收数据" in out
def test_inline_no_detail_zone_for_short_options(monkeypatch, capsys):
    import os
    import shutil
    from psyclaw.choices import _pick_inline
    monkeypatch.setattr(shutil, "get_terminal_size",
                        lambda fallback=None: os.terminal_size((100, 24)))
    _pick_inline(_single(), get_key=_feed(["ENTER"]))
    assert "▏" not in capsys.readouterr().out      # 短选项无需详情区
