"""v0.2 PR 评审修复回归测试(16 项 ≥80 置信度)+ 命令块执行特性。"""

from __future__ import annotations

import json
import zlib
from pathlib import Path

from psyclaw import repl as R


# --- fail-closed 确认(修复:_ask_yn EOF→True 导致免批准覆盖) -------------------

def test_hitl_confirm_fail_closed_non_tty():
    assert R._hitl_confirm("覆盖?") is False      # pytest 环境非 TTY → 必须 False


# --- read_file 守卫(修复:agent 工具缺 data/raw/密钥守卫) ----------------------

def test_read_denied_raw_and_secrets(tmp_path):
    assert R.read_denied(Path("data/raw/p.csv")) is not None
    assert R.read_denied(tmp_path / ".env") is not None
    assert R.read_denied(tmp_path / "id_rsa") is not None
    assert R.read_denied(tmp_path / "server.pem") is not None
    assert R.read_denied(tmp_path / "notes" / "draft.md") is None


def test_toolloop_read_file_refuses_raw(tmp_path):
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    (raw / "s.csv").write_text("x\n1\n", encoding="utf-8")
    from psyclaw.toolloop import build_tools
    out = build_tools(str(tmp_path))["read_file"]["run"](
        {"path": str(raw / "s.csv")})
    assert "拒绝读取" in out and "1" not in out.split(":")[-1]


# --- save 块嵌套围栏(修复:内容含 ```python 被截断且谎报已保存) -----------------

def test_save_block_keeps_nested_fences():
    reply = ("```save path=a.md\n# 笔记\n```python\nprint(1)\n```\n尾行\n```\n"
             "说明文字")
    blocks = R.parse_save_blocks(reply)
    assert len(blocks) == 1
    assert "print(1)" in blocks[0]["content"]
    assert blocks[0]["content"].endswith("尾行")


def test_strip_save_blocks_removes_content():
    reply = "前言\n```save path=a.md\n```read\nX\n```\n体\n```\n后语"
    stripped = R.strip_save_blocks(reply)
    assert "前言" in stripped and "后语" in stripped
    assert "X" not in stripped                    # save 内容里的 read 示例不外泄
    assert R.parse_read_requests(stripped) == []


# --- choices:围栏排除 + heuristic 开关(修复:计划任务清单弹选择器) --------------

def test_choices_skips_fenced_and_heuristic_flag():
    from psyclaw.choices import parse_choices
    fenced = "看示例:\n```\n- [ ] A\n- [ ] B\n```\n没有真选项"
    assert parse_choices(fenced) is None
    plan = "## TASKS\n- [ ] 任务一\n- [ ] 任务二"
    assert parse_choices(plan, heuristic=False) is None
    assert parse_choices(plan, heuristic=True) is not None


# --- 会话检索:FTS 零命中回落 LIKE(修复:连续中文 FTS 永不命中) ------------------

def test_search_cjk_falls_back_to_like(tmp_path):
    from psyclaw.embed import get_embedder
    from psyclaw.recall import ContextArchive
    a = ContextArchive(str(tmp_path), embedder=get_embedder(prefer="hash"))
    a.record("s1", "我想复现焦虑量表的信度分析", "回答")   # 无空格中文
    hits = a.search("量表")
    assert any(h["session"] == "s1" for h in hits)


# --- PDF 质量门(修复:latin-1 随机二进制 66% 过旧 0.6 阈值) ---------------------

def test_pdf_gate_rejects_random_binary(tmp_path):
    import random
    rnd = random.Random(7)
    raw = bytes(rnd.randrange(256) for _ in range(4000))
    pdf = (b"%PDF-1.4\n1 0 obj<</Filter/DCTDecode>>\nstream\n(" + raw
           + b")\nendstream\nendobj\n%%EOF")
    p = tmp_path / "scan.pdf"
    p.write_bytes(pdf)
    from psyclaw.pdf_extract import extract_pdf_text
    assert extract_pdf_text(p)["ok"] is False     # 乱码绝不 ok


# --- classify_csv 编码(修复:GBK CSV 炸掉 auto-loop) ---------------------------

def test_classify_csv_gbk_does_not_crash(tmp_path):
    p = tmp_path / "d.csv"
    p.write_bytes("组别,焦虑分\n对照,18\n".encode("gbk"))
    from psyclaw.autoloop import classify_csv, discover_backlog
    assert classify_csv(str(p)) == "data"
    discover_backlog(str(tmp_path))               # 不抛异常即可


# --- kg:无语料=人工核(修复:空语料把全部边判杜撰)+ mermaid 合法节点 -------------

def test_kg_verify_no_corpus_is_manual(tmp_path):
    from psyclaw.kg import KnowledgeGraph
    kg = KnowledgeGraph(str(tmp_path))
    kg.add_edge("焦虑", "construct", "研究见于", "Smith (2020)", "paper",
                source_ref="Smith (2020)")
    v = kg.verify(str(tmp_path))                  # 无 evidence_map
    assert v["manual_review"] is True
    assert v["no_orphan_relations"] is True and v["orphans"] == []


def test_kg_mermaid_uses_node_ids(tmp_path):
    from psyclaw.kg import KnowledgeGraph, render_mermaid
    kg = KnowledgeGraph(str(tmp_path))
    kg.add_edge('记忆"广度"', "construct", "见|于", "Smith (2020)", "paper",
                source_ref="Smith (2020)")
    out = render_mermaid(kg.subgraph('记忆"广度"'))
    assert 'n0["' in out and "-->|" in out        # nK["label"] 形式
    assert '"记忆"广度""' not in out              # 双引号已转义
    assert "见/于" in out                         # | 已转义


# --- status:blocked 取尾部(修复:>4000 字后显示最旧一条) ------------------------

def test_status_blocked_shows_latest(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    old = "\n## t0 — OLD 验收未过\n- x\n" + ("填充行\n" * 500)
    (notes / "blocked.md").write_text(old + "\n## t9 — NEW 验收未过\n- y\n",
                                      encoding="utf-8")
    from psyclaw.status import collect_status
    assert "NEW" in collect_status(str(tmp_path))["last_blocked"]


# --- 二进制嗅探(实测:伪装 .csv 的 zip 读成乱码) --------------------------------

def test_smart_excerpt_zip_disguised_as_csv(tmp_path):
    p = tmp_path / "研究1a.csv"
    p.write_bytes(b"PK\x03\x04" + zlib.compress(b"xlsx-ish") + b"\x00" * 50)
    from psyclaw.context import smart_excerpt
    out = smart_excerpt(p)
    assert "zip" in out.lower() or "ZIP" in out
    assert "PK" not in out.split(">")[-1][:10]    # 不注入二进制


# --- path_ingest 提示不再推荐已删命令(实测:模型据此调用 describe/stat) ----------

def test_data_hint_no_deleted_commands(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")
    from psyclaw.path_ingest import _data_metadata
    hint = _data_metadata(p)
    assert "describe" not in hint and "psyclaw stat" not in hint
    assert "analysis-loop" in hint


# --- 命令块执行(新特性:模型吐命令块 → 执行并回传,不再死胡同) --------------------

def test_parse_run_requests_kinds():
    reply = ("```psyclaw\nstatus\n```\n```shell\necho hi\n# 注释\n```\n"
             "```bash\npython -V\n```")
    reqs = R.parse_run_requests(reply)
    assert reqs == [{"kind": "psyclaw", "cmd": "status"},
                    {"kind": "shell", "cmd": "echo hi"},
                    {"kind": "shell", "cmd": "python -V"}]


def test_run_commands_dangerous_denied_without_confirm():
    msg, notes = R.run_commands([{"kind": "shell", "cmd": "git push --force origin x"}],
                                confirm=None)
    assert "已拒绝" in msg and any("危险" in n for n in notes)


def test_run_commands_executes_shell():
    # v0.3 安全加固:shell 须显式确认(fail-closed);确认到位后照常执行
    msg, _ = R.run_commands([{"kind": "shell", "cmd": "echo psyclaw-run-ok"}],
                            confirm=lambda c: True)
    assert "psyclaw-run-ok" in msg and "(rc=0)" in msg


# --- v0.3 安全加固(外审 HIGH):shell 每条 fail-closed,拒绝清单只是标签 -----------

def test_run_commands_shell_denied_without_confirm():
    """普通(非危险模式)shell 命令,无 confirm 也一律拒——拒绝清单不是安全边界。"""
    msg, notes = R.run_commands([{"kind": "shell", "cmd": "echo innocent"}],
                                confirm=None)
    assert "已拒绝" in msg and "shell 命令" in msg
    assert any("✗" in n for n in notes)
    assert "(rc=" not in msg  # 未执行(拒绝消息只回显命令,不含执行结果)


def test_run_commands_shell_denied_when_confirm_refuses():
    msg, _ = R.run_commands([{"kind": "shell", "cmd": "echo nope"}],
                            confirm=lambda c: False)
    assert "已拒绝" in msg


def test_run_commands_psyclaw_kind_auto_runs_without_confirm():
    """psyclaw 进程内子命令保持自动(自家 argparse,无 shell)。"""
    msg, notes = R.run_commands([{"kind": "psyclaw", "cmd": "version"}], confirm=None)
    assert "(rc=0)" in msg and any("⚙" in n for n in notes)


def test_run_commands_psyclaw_dangerous_still_needs_confirm():
    """psyclaw 类命令若命中危险模式(如参数里藏 rm -rf)同样须确认(纵深防御)。"""
    msg, _ = R.run_commands([{"kind": "psyclaw", "cmd": "clean rm -rf /tmp/x"}],
                            confirm=None)
    assert "已拒绝" in msg and "危险命令" in msg


def test_run_commands_confirm_called_per_shell_command():
    seen = []
    R.run_commands([{"kind": "shell", "cmd": "echo a"},
                    {"kind": "shell", "cmd": "echo b"}],
                   confirm=lambda c: (seen.append(c), True)[1])
    assert seen == ["echo a", "echo b"]


def test_run_psyclaw_version_inprocess():
    out = R._run_psyclaw_cmd("psyclaw version")
    assert "(rc=0)" in out and "psyclaw" in out


def test_run_psyclaw_interactive_blocked():
    out = R._run_psyclaw_cmd("repl")
    assert "未执行" in out and "交互式" in out


def test_run_psyclaw_unknown_command_reports_error():
    out = R._run_psyclaw_cmd("describe data.csv")   # 已删除的统计命令
    assert "(rc=" in out and "(rc=0)" not in out    # 报错回传,模型可自纠
