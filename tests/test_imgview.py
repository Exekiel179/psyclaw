"""终端内联图片渲染测试 —— 纯字节转义 + 环境探测 + 路径提取(不依赖真实终端)。"""

from __future__ import annotations

import base64

from psyclaw import imgview

# 1x1 PNG(合法最小图),测试用真实字节
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


# -- is_image / find_image_paths -----------------------------------------
def test_is_image():
    assert imgview.is_image("a.png") and imgview.is_image("A.JPG")
    assert not imgview.is_image("a.txt") and not imgview.is_image("a.svg")


def test_find_image_paths():
    txt = "散点图已保存为 behavior_brain_corr.png\n又存了 figures/forest.jpg 和 x.csv"
    got = imgview.find_image_paths(txt)
    assert "behavior_brain_corr.png" in got
    assert "figures/forest.jpg" in got
    assert all(not p.endswith(".csv") for p in got)


def test_find_image_paths_dedup_and_empty():
    assert imgview.find_image_paths("a.png a.png") == ["a.png"]
    assert imgview.find_image_paths("") == []


# -- 环境探测(纯) -------------------------------------------------------
def test_proto_from_env_kitty():
    assert imgview._proto_from_env({"KITTY_WINDOW_ID": "1"}) == "kitty"
    assert imgview._proto_from_env({"TERM": "xterm-kitty"}) == "kitty"


def test_proto_from_env_iterm2_family():
    for prog in ("iTerm.app", "WezTerm", "vscode", "WarpTerminal"):
        assert imgview._proto_from_env({"TERM_PROGRAM": prog}) == "iterm2"
    assert imgview._proto_from_env({"LC_TERMINAL": "iTerm2"}) == "iterm2"


def test_proto_from_env_unsupported_and_tmux():
    assert imgview._proto_from_env({"TERM_PROGRAM": "Apple_Terminal"}) is None
    assert imgview._proto_from_env({"TERM": "screen-256color",
                                    "TERM_PROGRAM": "iTerm.app"}) is None  # tmux/screen 不支持


def test_supports_inline_force_override(monkeypatch):
    assert imgview.supports_inline(force="none") is None
    assert imgview.supports_inline(force="iterm2") == "iterm2"
    assert imgview.supports_inline(force="kitty") == "kitty"


# -- 转义生成(纯) -------------------------------------------------------
def test_render_iterm2_shape():
    esc = imgview.render_iterm2("plot.png", _PNG)
    assert esc.startswith("\033]1337;File=inline=1;")
    assert f"size={len(_PNG)}" in esc
    assert base64.b64encode(_PNG).decode() in esc
    assert esc.endswith("\a\n")


def test_render_kitty_shape():
    esc = imgview.render_kitty(_PNG)
    assert "\033_G" in esc and "a=T,f=100," in esc
    assert base64.b64encode(_PNG).decode() in esc


# -- render_escape 端到端(用临时文件 + force 绕过终端探测)----------------
def test_render_escape_iterm2(tmp_path):
    p = tmp_path / "fig.png"
    p.write_bytes(_PNG)
    esc = imgview.render_escape(p, force="iterm2")
    assert esc and esc.startswith("\033]1337;File=inline=1;")


def test_render_escape_kitty_png(tmp_path):
    p = tmp_path / "fig.png"
    p.write_bytes(_PNG)
    assert imgview.render_escape(p, force="kitty").startswith("\033_G")


def test_render_escape_kitty_rejects_nonpng(tmp_path):
    p = tmp_path / "fig.jpg"
    p.write_bytes(_PNG)                       # 内容不重要,kitty 只按后缀限 PNG
    assert imgview.render_escape(p, force="kitty") is None


def test_render_escape_none_when_unsupported(tmp_path):
    p = tmp_path / "fig.png"
    p.write_bytes(_PNG)
    assert imgview.render_escape(p, force="none") is None


def test_render_escape_rejects_nonimage_and_missing(tmp_path):
    txt = tmp_path / "a.txt"
    txt.write_text("hi")
    assert imgview.render_escape(txt, force="iterm2") is None
    assert imgview.render_escape(tmp_path / "nope.png", force="iterm2") is None


def test_render_escape_rejects_oversize(tmp_path, monkeypatch):
    monkeypatch.setattr(imgview, "MAX_IMG_BYTES", 10)
    p = tmp_path / "big.png"
    p.write_bytes(_PNG)                       # 67 字节 > 10
    assert imgview.render_escape(p, force="iterm2") is None
