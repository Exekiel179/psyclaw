"""feat-139:AJS 目标期刊技能包安装——resolve 纯函数 / 稀疏检出 fail-safe /
mirror github 回退 / loader 三层 glob / CLI journal install & start --journal。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from psyclaw import ajs

_PACKS = ["AAAI-Skills", "American-Economic-Review-Skills",
          "China-Economic-Quarterly-Skills", "Caijing-Yanjiu",
          "Journal-of-Finance-Skills", "Management-Science-Skills"]


# ---- resolve_pack:纯函数,无网可测 -------------------------------------------

def test_resolve_exact_name():
    r = ajs.resolve_pack("AAAI", _PACKS)
    assert r["match"] == "AAAI-Skills"


def test_resolve_full_display_name():
    r = ajs.resolve_pack("American Economic Review", _PACKS)
    assert r["match"] == "American-Economic-Review-Skills"


def test_resolve_english_abbrev_alias():
    r = ajs.resolve_pack("AER", _PACKS)
    assert r["match"] == "American-Economic-Review-Skills"


def test_resolve_chinese_journal_to_pinyin_dir():
    r = ajs.resolve_pack("财经研究", _PACKS)
    assert r["match"] == "Caijing-Yanjiu"


def test_resolve_ambiguous_lists_candidates():
    r = ajs.resolve_pack("Economic", _PACKS)
    assert r["match"] is None
    assert set(r["candidates"]) >= {"American-Economic-Review-Skills",
                                    "China-Economic-Quarterly-Skills"}


def test_resolve_zero_hit_gives_close_candidates():
    r = ajs.resolve_pack("Managment Sciense", _PACKS)   # 拼错也给近似
    assert r["match"] is None or r["match"] == "Management-Science-Skills"
    if r["match"] is None:
        assert "Management-Science-Skills" in r["candidates"]


def test_resolve_empty_name():
    r = ajs.resolve_pack("", _PACKS)
    assert r["match"] is None and r["candidates"] == []


# ---- list_packs:mock 网络 ----------------------------------------------------

def test_list_packs_parses_top_level_trees(monkeypatch):
    payload = {"tree": [
        {"path": "AAAI-Skills", "type": "tree"},
        {"path": "Caijing-Yanjiu", "type": "tree"},
        {"path": ".claude-plugin", "type": "tree"},      # 插件市场元数据,不是期刊包
        {"path": "README.md", "type": "blob"},
    ]}

    class _Resp:
        def read(self):
            return json.dumps(payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(ajs, "_packs_cache", None)
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Resp())
    r = ajs.list_packs()
    assert r["ok"] is True
    assert r["packs"] == ["AAAI-Skills", "Caijing-Yanjiu"]


def test_list_packs_offline_fail_safe(monkeypatch):
    def boom(*a, **k):
        raise OSError("no network")
    monkeypatch.setattr(ajs, "_packs_cache", None)
    monkeypatch.setattr("urllib.request.urlopen", boom)
    r = ajs.list_packs()
    assert r["ok"] is False and r["packs"] == []


# ---- install_pack:mock subprocess,fail-safe ---------------------------------

def _fake_git_ok(record):
    """假 git:clone 建 repo 目录,checkout 落包内容。"""
    def _run(argv, **kw):
        record.append(argv)
        if argv[:2] == ["git", "clone"]:
            Path(argv[-1]).mkdir(parents=True, exist_ok=True)
        if "checkout" in argv:
            repo = Path(argv[argv.index("-C") + 1])
            sk = repo / "AAAI-Skills" / "skills" / "abstract" / "SKILL.md"
            sk.parent.mkdir(parents=True, exist_ok=True)
            sk.write_text("---\nname: aaai-abstract\n---\n", encoding="utf-8")
        class R:
            returncode = 0
            stdout = stderr = ""
        return R()
    return _run


def test_install_pack_sparse_checkout_success(monkeypatch, tmp_path):
    record: list = []
    monkeypatch.setattr("subprocess.run", _fake_git_ok(record))
    monkeypatch.setattr("psyclaw.mirror.github_clone_url", lambda u: u)
    dest = tmp_path / ".claude" / "skills"
    r = ajs.install_pack("AAAI-Skills", dest)
    assert r["ok"] is True
    assert (dest / "AAAI-Skills" / "skills" / "abstract" / "SKILL.md").exists()
    flat = [" ".join(a) for a in record]
    assert any("--filter=blob:none" in c and "--depth" in c for c in flat)
    assert any("sparse-checkout" in c for c in flat)


def test_install_pack_already_installed_skips(tmp_path):
    dest = tmp_path / ".claude" / "skills"
    (dest / "AAAI-Skills").mkdir(parents=True)
    r = ajs.install_pack("AAAI-Skills", dest)
    assert r["ok"] is True and "已存在" in r["note"]


def test_install_pack_no_git_gives_manual_commands(monkeypatch, tmp_path):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda x: None)
    r = ajs.install_pack("AAAI-Skills", tmp_path / "skills")
    assert r["ok"] is False
    assert "git" in r["note"] and "sparse-checkout" in r["note"]   # 手动命令


def test_install_pack_clone_failure_fail_safe(monkeypatch, tmp_path):
    def _run(argv, **kw):
        class R:
            returncode = 128
            stdout = ""
            stderr = "fatal: unable to access"
        return R()
    monkeypatch.setattr("subprocess.run", _run)
    monkeypatch.setattr("psyclaw.mirror.github_clone_url", lambda u: u)
    r = ajs.install_pack("AAAI-Skills", tmp_path / "skills")   # 不抛
    assert r["ok"] is False and "sparse-checkout" in r["note"]


# ---- mirror:github 回退 -------------------------------------------------------

def test_github_clone_url_passthrough_when_reachable(monkeypatch):
    from psyclaw import mirror
    monkeypatch.setattr(mirror, "github_reachable", lambda timeout=4.0: True)
    u = "https://github.com/brycewang-stanford/awesome-journal-skills"
    assert mirror.github_clone_url(u) == u


def test_github_clone_url_rewrites_on_force_mirror(monkeypatch):
    from psyclaw import mirror
    monkeypatch.setenv("PSYCLAW_FORCE_MIRROR", "1")
    mirror._probe_cache.clear()
    u = "https://github.com/brycewang-stanford/awesome-journal-skills"
    out = mirror.github_clone_url(u)
    assert out != u and "brycewang-stanford/awesome-journal-skills" in out


# ---- loader:认 AJS 三层布局 <包>/skills/<技能>/SKILL.md -----------------------

def test_loader_finds_ajs_pack_layout(tmp_path, monkeypatch):
    from psyclaw.skills.loader import list_skills
    root = tmp_path / ".claude" / "skills"
    sk = root / "AAAI-Skills" / "skills" / "abstract-writing" / "SKILL.md"
    sk.parent.mkdir(parents=True)
    sk.write_text("---\nname: aaai-abstract-writing\ndescription: 摘要规范\n---\n",
                  encoding="utf-8")
    names = {s["name"] for s in list_skills(str(tmp_path))}
    assert "aaai-abstract-writing" in names


# ---- CLI:journal install / start --journal -----------------------------------

def _mock_ajs(monkeypatch, packs=("AAAI-Skills",), ok=True):
    monkeypatch.setattr(ajs, "list_packs",
                        lambda **k: {"ok": True, "packs": list(packs), "note": ""})
    installed: list = []

    def _install(pack, dest, **k):
        installed.append((pack, str(dest)))
        return {"ok": ok, "path": str(Path(dest) / pack), "note": "", "mirror": False}
    monkeypatch.setattr(ajs, "install_pack", _install)
    return installed


def test_cli_journal_install_writes_target_journal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    installed = _mock_ajs(monkeypatch)
    from psyclaw.cli import cmd_journal
    rc = cmd_journal(argparse.Namespace(journal_id="install", name=["AAAI"],
                                        global_install=False))
    assert rc == 0
    assert installed and installed[0][0] == "AAAI-Skills"
    assert str(tmp_path / ".claude" / "skills") in installed[0][1]
    conf = (tmp_path / ".psyclaw" / "config.yaml").read_text(encoding="utf-8")
    assert "target_journal" in conf and "AAAI" in conf


def test_cli_journal_install_global_dest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    installed = _mock_ajs(monkeypatch)
    from psyclaw.cli import cmd_journal
    rc = cmd_journal(argparse.Namespace(journal_id="install", name=["AAAI"],
                                        global_install=True))
    assert rc == 0
    assert str(Path.home() / ".claude" / "skills") in installed[0][1]


def test_cli_journal_browse_unaffected(capsys):
    from psyclaw.cli import cmd_journal
    rc = cmd_journal(argparse.Namespace(journal_id=None, name=[],
                                        global_install=False))
    assert rc == 0
    assert "期刊画像目录" in capsys.readouterr().out    # 既有行为不回归


def test_cmd_start_journal_step_noninteractive(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    installed = _mock_ajs(monkeypatch)
    from psyclaw.cli import cmd_start
    rc = cmd_start(argparse.Namespace(intent="投 AAAI", sandbox=False,
                                      journal="AAAI", journal_global=False))
    assert rc == 0
    assert installed and installed[0][0] == "AAAI-Skills"
    conf = (tmp_path / ".psyclaw" / "config.yaml").read_text(encoding="utf-8")
    assert "target_journal" in conf


def test_cmd_start_without_journal_attr_still_works(tmp_path, monkeypatch):
    """老调用形态(无 journal 属性、无终端)不回归、不被 input 卡死。"""
    monkeypatch.chdir(tmp_path)
    from psyclaw.cli import cmd_start
    rc = cmd_start(argparse.Namespace(intent="做统计", sandbox=False))
    assert rc == 0


def test_cmd_start_install_failure_does_not_break_start(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _mock_ajs(monkeypatch, ok=False)
    from psyclaw.cli import cmd_start
    rc = cmd_start(argparse.Namespace(intent="投 AAAI", sandbox=False,
                                      journal="AAAI", journal_global=False))
    assert rc == 0                                     # 装包失败不中断 start


# ---- 查无匹配的落地(feat-194 A):非失败,给通用高标准/内置画像出路 -----------

def test_uncovered_journal_gives_generic_standard_not_deadend(
        tmp_path, monkeypatch, capsys):
    """NHB 这类内置与 AJS 都没有的刊:明确告知套用通用高标准,不读成失败。"""
    monkeypatch.chdir(tmp_path)
    _mock_ajs(monkeypatch, packs=("Nature-Geoscience-Skills",))
    from psyclaw.cli import cmd_journal
    rc = cmd_journal(argparse.Namespace(journal_id="install",
                                        name=["Nature Human Behaviour"],
                                        global_install=False))
    out = capsys.readouterr().out
    assert "这不是死路" in out
    assert "JARS" in out and "效应量" in out          # 点明兜底的通用高标准
    assert "官方投稿指南" in out                       # 指清边界:细节手动核
    assert rc == 1                                     # 没装成包,但不是错误语义


def test_uncovered_but_builtin_profile_reports_covered(
        tmp_path, monkeypatch, capsys):
    """内置画像已覆盖的刊(psych-science)不在 AJS 里:报「已覆盖」,返回 0。"""
    monkeypatch.chdir(tmp_path)
    _mock_ajs(monkeypatch, packs=("AAAI-Skills",))     # AJS 无 psych-science
    from psyclaw.cli import cmd_journal
    rc = cmd_journal(argparse.Namespace(journal_id="install",
                                        name=["psych-science"],
                                        global_install=False))
    out = capsys.readouterr().out
    assert "内置画像覆盖" in out and "psych-science" in out
    assert rc == 0


# ---- check 默认带 target_journal(--journal 可覆盖)---------------------------

def test_check_defaults_to_target_journal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from psyclaw.config import set_project_config
    set_project_config("target_journal", "xinlixuebao", ".")
    seen = {}

    def _fake_run_check(draft=None, journal=None, project_dir=".",
                        research_type="quant"):
        seen["journal"] = journal
        return {"passed": True, "sections": []}
    monkeypatch.setattr("psyclaw.checkup.run_check", _fake_run_check)
    monkeypatch.setattr("psyclaw.checkup.print_check", lambda res: None)
    from psyclaw.cli import cmd_check
    cmd_check(argparse.Namespace(draft=None, journal=None, research_type="quant"))
    assert seen["journal"] == "xinlixuebao"
    cmd_check(argparse.Namespace(draft=None, journal="psych-science",
                                 research_type="quant"))
    assert seen["journal"] == "psych-science"          # 显式 --journal 覆盖
