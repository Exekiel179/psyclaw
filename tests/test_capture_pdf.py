"""下好的 PDF 自动收进项目(feat-190)。

用户问「不能帮我下载么」——不能直接下:登录后的会话在**浏览器**里,Python 侧拿不到
那个 cookie。但用户点一下「下载」本就是最自然的动作,真正多余的是让他记住
「另存到 outputs/pdfs/、还得起对文件名」。这里把那份麻烦接过来:盯住系统下载目录,
新 PDF 一出现就收走并按 作者_年份_题名 改名。

两条纪律:
- 只认**新出现**的文件(先拍快照)——不去动用户下载目录里原有的东西;
- 必须过 %PDF 魔数——出版社的登录页/错误页常被存成 .pdf,靠扩展名会把垃圾收进来。
"""
from __future__ import annotations

from psyclaw.psych.paywall import _safe_name, capture_from_downloads
from psyclaw.toolloop import build_tools

PDF = b"%PDF-1.7\n" + b"x" * 2048


def _clock_seq(n=50):
    """确定性时钟:每次调用推进 1 秒,避免测试真的 sleep。"""
    t = {"v": 0.0}

    def _c():
        t["v"] += 1.0
        return t["v"]
    return _c


def _appears(dl, name, data=PDF):
    """在轮询间隙才出现的文件——模拟「用户此刻点了下载」。
    快照是在调用开始时拍的,所以文件必须在那之后出现才算「新下的」。
    """
    def _sleep(_s, _st={"n": 0}):
        _st["n"] += 1
        if _st["n"] == 1:
            (dl / name).write_bytes(data)
    return _sleep
def test_captures_new_pdf_and_renames(tmp_path):
    dl, out = tmp_path / "dl", tmp_path / "out"
    dl.mkdir()
    r = capture_from_downloads(doi="10.1/x", out_dir=out, name_hint="Ang_2025_Doom",
                               src_dir=dl, timeout=5, poll=0,
                               clock=_clock_seq(),
                               sleeper=_appears(dl, "raw-download.pdf"))
    assert r["ok"] is True
    assert (out / "Ang_2025_Doom.pdf").is_file()
    assert not (dl / "raw-download.pdf").exists()      # 已移走,不是复制


def test_ignores_preexisting_files(tmp_path):
    """用户下载目录里原有的 PDF 不能被顺手收走。"""
    dl, out = tmp_path / "dl", tmp_path / "out"
    dl.mkdir()
    (dl / "old.pdf").write_bytes(PDF)
    r = capture_from_downloads(out_dir=out, src_dir=dl, timeout=3, poll=0,
                               sleeper=lambda s: None, clock=_clock_seq())
    assert r["ok"] is False and r.get("timeout") is True
    assert (dl / "old.pdf").is_file()                  # 原文件原封不动


def test_rejects_non_pdf_content(tmp_path):
    """登录页/错误页存成 .pdf 是常见坑——靠魔数拦住,别把垃圾收进项目。"""
    dl, out = tmp_path / "dl", tmp_path / "out"
    dl.mkdir()
    r = capture_from_downloads(out_dir=out, src_dir=dl, timeout=5, poll=0,
                               clock=_clock_seq(),
                               sleeper=_appears(dl, "login.pdf",
                                                b"<!DOCTYPE html><html>Sign in"))
    assert r["ok"] is False and "不是 PDF" in r["note"]
    assert not list(out.glob("*.pdf"))


def test_waits_for_partial_download(tmp_path):
    """.crdownload 还在 = 没下完,不能半截收走。"""
    dl, out = tmp_path / "dl", tmp_path / "out"
    dl.mkdir()
    (dl / "a.crdownload").write_bytes(b"partial")
    r = capture_from_downloads(out_dir=out, src_dir=dl, timeout=3, poll=0,
                               sleeper=lambda s: None, clock=_clock_seq())
    assert r["ok"] is False and r.get("timeout") is True


def test_does_not_overwrite_existing(tmp_path):
    dl, out = tmp_path / "dl", tmp_path / "out"
    dl.mkdir()
    out.mkdir()
    (out / "P.pdf").write_bytes(b"%PDF-old")
    r = capture_from_downloads(out_dir=out, name_hint="P", src_dir=dl,
                               timeout=5, poll=0, clock=_clock_seq(),
                               sleeper=_appears(dl, "new.pdf"))
    assert r["ok"] is True
    assert (out / "P.pdf").read_bytes() == b"%PDF-old"   # 旧文件没被覆盖
    assert (out / "P-1.pdf").is_file()


def test_missing_downloads_dir_is_reported(tmp_path):
    r = capture_from_downloads(out_dir=tmp_path / "out",
                               src_dir=tmp_path / "nope", timeout=1, poll=0,
                               sleeper=lambda s: None)
    assert r["ok"] is False and "找不到下载目录" in r["note"]


def test_safe_name_sanitizes_and_falls_back():
    assert _safe_name("Ang 2025: Doom/Scroll", "10.1/x").endswith(".pdf")
    assert "/" not in _safe_name("a/b", "10.1/x")
    assert _safe_name("", "10.1/x").startswith("paper-")
    assert _safe_name("已有.pdf", "10.1/x") == "已有.pdf"   # 不重复加后缀


def test_tool_registered_needs_approval():
    t = build_tools(".")
    assert "lit_capture_pdf" in t
    assert t["lit_capture_pdf"]["side_effect"] is True     # 会移动用户文件,先问


def test_handoff_message_no_longer_demands_manual_path(tmp_path):
    """引导文案不该再要求用户另存到指定路径 + 起对文件名。"""
    from psyclaw.psych.paywall import browser_handoff, handoff_message
    r = browser_handoff("10.1/x", project_dir=str(tmp_path), opener=lambda u: True)
    msg = handoff_message(r, "10.1/x")
    assert "lit_capture_pdf" in msg
    assert "不用另存到别处" in msg
