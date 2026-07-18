"""feat(cite 重定位):删方法学背书静态库(evidence.json),cite 改做引用保真核查。

用户判断:静态背书库不现实(既不全也会过时,跟"引用要可核实"矛盾)。删掉;
需要文献依据走真实检索(lit)。cite 从"查背书库"变成"引文核查"(反杜撰参考文献)。
"""
from __future__ import annotations

import os


def test_evidence_json_removed():
    from psyclaw.psych import knowledge as K
    p = os.path.join(os.path.dirname(K.__file__), "evidence.json")
    assert not os.path.exists(p), "evidence.json 应已删除"


def test_print_evidence_gone():
    from psyclaw.psych import knowledge as K
    assert not hasattr(K, "print_evidence"), "print_evidence 应已移除"


def test_relevant_knowledge_ok_without_evidence():
    """删掉 evidence 后,按消息注入知识仍正常(方法/设计条目还在)。"""
    from psyclaw.context import relevant_knowledge
    out = relevant_knowledge("帮我做中介效应 mediation 分析")
    assert isinstance(out, str)


def test_cite_command_now_runs_audit():
    """cite 双模:给稿件走引文核查(引用文章走 --make,见 test_reference)。"""
    import argparse
    from psyclaw.cli import build_parser, cmd_cite
    p = build_parser()
    args = p.parse_args(["cite", "notes/lit_review.md"])
    assert args.func is cmd_cite               # 统一入口 cmd_cite 分派
    assert args.make is None                    # 无 --make → 核查模式
    # 分派到核查:给不存在的稿件,run_citation_audit 应被调用(核查语义保留)
    import psyclaw.cli as cli
    called = {}
    orig = cli.cmd_cite_check
    cli.cmd_cite_check = lambda a: called.setdefault("audit", True) or 0
    try:
        cli.cmd_cite(argparse.Namespace(make=None, manuscript="x.md",
                                        project=".", journal=None))
    finally:
        cli.cmd_cite_check = orig
    assert called.get("audit")


def test_cite_audit_runs_on_draft(tmp_path, capsys):
    import argparse
    d = tmp_path / "draft.md"
    d.write_text("研究表明 Smith (2020) 支持该假设。\n", encoding="utf-8")
    from psyclaw.cli import cmd_cite_check
    rc = cmd_cite_check(argparse.Namespace(manuscript=str(d),
                                           project=str(tmp_path), journal=None))
    assert rc in (0, 1)
    assert "引用保真核查" in capsys.readouterr().out


def test_cite_still_catalogued():
    """命令目录仍收录 cite(不悬空)。"""
    from psyclaw.cli import COMMAND_CATEGORIES
    flat = [c for _t, cs in COMMAND_CATEGORIES for c in cs]
    assert "cite" in flat
