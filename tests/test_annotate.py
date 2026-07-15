"""feat-142:annotate 命令——给代码写注释(按 assist_level 定密度)+ --review 审查。"""
from __future__ import annotations

import argparse

from psyclaw.annotate import build_annotate_prompt, run_annotate


class _FakeProvider:
    name = "fake"

    def __init__(self, reply):
        self.reply = reply
        self.seen = []

    def chat(self, messages, system=""):
        self.seen.append((system, messages))
        return iter([self.reply])


_CODE = "import pingouin as pg\nres = pg.ttest(a, b)\nprint(res)\n"


# ---- 提示构建:注释密度随协助水平变 -------------------------------------------

def test_prompt_novice_dense_comments():
    sys_p, user_p = build_annotate_prompt(_CODE, "t.py", "novice")
    assert "逐段" in sys_p or "白话" in sys_p
    assert _CODE.strip() in user_p


def test_prompt_expert_sparse_comments():
    sys_p, _ = build_annotate_prompt(_CODE, "t.py", "expert")
    assert "非显然" in sys_p or "精简" in sys_p


def test_prompt_review_mode_reviews_not_rewrites():
    sys_p, _ = build_annotate_prompt(_CODE, "t.py", "standard", review=True)
    assert "审查" in sys_p
    assert "效应量" in sys_p or "统计" in sys_p        # 统计规范也在审查面里
    assert "不要改写" in sys_p or "不修改" in sys_p


# ---- run_annotate ---------------------------------------------------------------

def test_annotate_returns_annotated_code(tmp_path):
    f = tmp_path / "t.py"
    f.write_text(_CODE, encoding="utf-8")
    prov = _FakeProvider("```python\n# Welch t 检验\n" + _CODE + "```")
    r = run_annotate(str(f), provider=prov)
    assert r["ok"] is True
    assert "# Welch t 检验" in r["text"]
    assert "```" not in r["text"]                      # 围栏已剥
    assert f.read_text(encoding="utf-8") == _CODE      # 默认不写回


def test_annotate_write_creates_backup(tmp_path):
    f = tmp_path / "t.py"
    f.write_text(_CODE, encoding="utf-8")
    prov = _FakeProvider("# 注释\n" + _CODE)
    r = run_annotate(str(f), provider=prov, write=True)
    assert r["ok"] is True
    assert (tmp_path / "t.py.bak").read_text(encoding="utf-8") == _CODE
    assert "# 注释" in f.read_text(encoding="utf-8")


def test_annotate_write_refuses_suspicious_shrink(tmp_path):
    """LLM 输出把代码弄丢(行数骤减)时拒绝写回,防注释操作变成删代码。"""
    f = tmp_path / "t.py"
    f.write_text(_CODE * 10, encoding="utf-8")
    prov = _FakeProvider("# 只剩一行")
    r = run_annotate(str(f), provider=prov, write=True)
    assert r["ok"] is False
    assert f.read_text(encoding="utf-8") == _CODE * 10   # 原文件不动


def test_annotate_mock_provider_clear_downgrade(tmp_path):
    f = tmp_path / "t.py"
    f.write_text(_CODE, encoding="utf-8")

    class _Mock:
        name = "mock"

        def chat(self, messages, system=""):
            return iter(["(mock)"])
    r = run_annotate(str(f), provider=_Mock())
    assert r["ok"] is False and "config" in r["note"]   # 指路 psyclaw config


def test_annotate_missing_file(tmp_path):
    r = run_annotate(str(tmp_path / "nope.py"), provider=_FakeProvider("x"))
    assert r["ok"] is False


def test_review_mode_never_touches_file(tmp_path):
    f = tmp_path / "t.py"
    f.write_text(_CODE, encoding="utf-8")
    prov = _FakeProvider("审查意见:①未报效应量……")
    r = run_annotate(str(f), provider=prov, review=True, write=True)
    assert r["ok"] is True and "审查意见" in r["text"]
    assert f.read_text(encoding="utf-8") == _CODE       # review 绝不改文件
    assert not (tmp_path / "t.py.bak").exists()


# ---- CLI ------------------------------------------------------------------------

def test_cmd_annotate_wiring(tmp_path, monkeypatch, capsys):
    f = tmp_path / "t.py"
    f.write_text(_CODE, encoding="utf-8")
    monkeypatch.setattr("psyclaw.annotate.run_annotate",
                        lambda path, review=False, write=False, provider=None:
                        {"ok": True, "text": "# 注释后代码", "note": ""})
    from psyclaw.cli import cmd_annotate
    rc = cmd_annotate(argparse.Namespace(file=str(f), review=False, write=False))
    assert rc == 0
    assert "# 注释后代码" in capsys.readouterr().out


def test_annotate_in_command_catalog():
    from psyclaw.cli import COMMAND_CATEGORIES
    flat = [c for _t, cs in COMMAND_CATEGORIES for c in cs]
    assert "annotate" in flat
