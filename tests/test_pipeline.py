"""一句话编排流水线测试 —— 总验收是 fail-closed 的产品规格。

运行:python -m pytest tests/ 或 python tests/test_pipeline.py
原则:
  - 澄清未完成 → 流水线硬停(返回 1),不产出稿(CLARIFY.complete)。
  - 总验收 fail-closed:未评审 / 评审非 ACCEPT|MINOR / 仍有 BLOCKING / 统计门禁
    阻断 → 不算"过门禁的稿";不能把"没评审"当作通过。
  - 端到端跑通(mock provider)应产出四象限产物 + 机器可读 notes/pipeline_summary.json。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw import pipeline  # noqa: E402
from psyclaw.pipeline import pipeline_verdict, run_pipeline  # noqa: E402

# 全部 17 槽位 resolved 的澄清卡(check_card 只数 `| <id> | resolved |` 行)。
from psyclaw.psych.clarify import SLOTS  # noqa: E402

PANEL_ACCEPT = """\
### R1
扎实,效应量与 CI 齐备。
RECOMMENDATION: ACCEPT

### R2
RECOMMENDATION: ACCEPT

### R3
RECOMMENDATION: ACCEPT

## REQUIRED REVISIONS
- [ ] [MINOR] 个别错字
"""


class _SeqProvider:
    """按调用顺序吐预设文本的 stub provider(整段一次性 yield)。"""

    name = "seq"

    def __init__(self, outs: list[str]) -> None:
        self._outs = list(outs)
        self._i = 0

    def chat(self, messages: list, system: str = ""):
        out = self._outs[min(self._i, len(self._outs) - 1)]
        self._i += 1
        yield out


def _patched(provider, fn):
    """临时把 psyclaw.providers.get_provider 换成返回 provider 的桩。"""
    import psyclaw.providers as prov
    orig = prov.get_provider
    prov.get_provider = lambda conf: provider
    try:
        return fn()
    finally:
        prov.get_provider = orig


def _resolved_card(proj: Path) -> None:
    """写一张全部 resolved 的澄清卡。"""
    (proj / "notes").mkdir(parents=True, exist_ok=True)
    lines = ["# 澄清卡", "", "| slot | status | answer |", "|---|---|---|"]
    for sid, *_ in SLOTS:
        lines.append(f"| {sid} | resolved | x |")
    (proj / "notes" / "clarification.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# pipeline_verdict —— 纯函数,fail-closed
# ---------------------------------------------------------------------------

def test_verdict_pass_when_all_green():
    rev = {"decision": "ACCEPT", "passed": True, "n_blocking": 0}
    v = pipeline_verdict(True, {"passed": True, "blocking": []}, rev)
    assert v["overall_passed"] is True
    assert v["gates_ok"] and v["review_ok"] and v["clarify_ok"]
    assert v["reasons"] == []


def test_verdict_minor_decision_passes():
    # MINOR(小修)且零 BLOCKING 视为过门禁。
    rev = {"decision": "MINOR", "n_blocking": 0}
    v = pipeline_verdict(True, None, rev)
    assert v["overall_passed"] is True
    assert v["gates_status"] == "n/a"      # 无统计产出 → n/a 不阻断


def test_verdict_no_review_is_failclosed():
    # 没评审不能当通过。
    v = pipeline_verdict(True, None, None)
    assert v["overall_passed"] is False
    assert any("未跑同行评审" in r for r in v["reasons"])


def test_verdict_major_blocks():
    rev = {"decision": "MAJOR", "n_blocking": 1}
    v = pipeline_verdict(True, {"passed": True, "blocking": []}, rev)
    assert v["overall_passed"] is False
    assert v["review_ok"] is False


def test_verdict_blocking_items_block_even_if_minor():
    # 编辑决定 MINOR 但仍有 BLOCKING 修订未消 → 不过。
    rev = {"decision": "MINOR", "n_blocking": 2}
    v = pipeline_verdict(True, None, rev)
    assert v["overall_passed"] is False
    assert any("BLOCKING" in r for r in v["reasons"])


def test_verdict_stat_gate_block_blocks_overall():
    rev = {"decision": "ACCEPT", "n_blocking": 0}
    gate = {"passed": False, "blocking": [{"gate": "STAT.effect_size"}]}
    v = pipeline_verdict(True, gate, rev)
    assert v["overall_passed"] is False
    assert v["gates_status"] == "blocked"


def test_verdict_clarify_false_blocks():
    rev = {"decision": "ACCEPT", "n_blocking": 0}
    v = pipeline_verdict(False, None, rev)
    assert v["overall_passed"] is False
    assert v["clarify_ok"] is False


# ---------------------------------------------------------------------------
# run_pipeline —— 端到端(stub provider,不依赖真实 LLM / 网络)
# ---------------------------------------------------------------------------

def test_pipeline_blocks_when_clarification_incomplete():
    # 没有澄清卡 → CLARIFY.complete 拦截,返回 1,不产出稿。
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        rc = _patched(_SeqProvider(["x"]), lambda: run_pipeline(
            topic="探究 X 对 Y 的影响", project_dir=str(proj), auto=True))
        assert rc == 1
        assert not (proj / "outputs" / "report.md").exists()
        summ = json.loads((proj / "notes" / "pipeline_summary.json")
                          .read_text(encoding="utf-8"))
        assert summ["stopped_at"] == "clarify"
        assert summ["overall_passed"] is False


def test_pipeline_end_to_end_produces_all_artifacts():
    # 澄清完成 → 四象限全跑通,产出综述/设计/稿/评审/总验收。
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        _resolved_card(proj)
        # 调用顺序:① 文献 ② 设计 ③(无数据跳过统计)④ 写作 ⑤ 评审面板。
        seq = _SeqProvider(["# 背景综述\n核心构念 …",
                            "# 研究设计\n假设 H1 …",
                            "# 研究稿\n结果显著,d=0.5 [0.1, 0.9]。",
                            PANEL_ACCEPT])
        rc = _patched(seq, lambda: run_pipeline(
            topic="探究 X 对 Y 的影响", project_dir=str(proj), auto=True))
        assert rc == 0
        assert (proj / "notes" / "lit_review.md").exists()
        assert (proj / "notes" / "design.md").exists()
        assert (proj / "outputs" / "report.md").exists()
        assert (proj / "notes" / "review_panel.json").exists()
        summ = json.loads((proj / "notes" / "pipeline_summary.json")
                          .read_text(encoding="utf-8"))
        # 评审 ACCEPT + 无统计产出(n/a) + 澄清完成 → 总验收通过。
        assert summ["overall_passed"] is True
        assert summ["review_decision"] == "ACCEPT"
        assert summ["gates_status"] == "n/a"
        assert summ["final_draft"] == "outputs/report.md"


def test_pipeline_failclosed_when_review_not_accept():
    # mock 风格面板不含 RECOMMENDATION → 无同行推荐 → 决定 MAJOR → 不过门禁,
    # 但流水线仍跑通(返回 0,交人工),summary 记录 BLOCK。
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        _resolved_card(proj)
        seq = _SeqProvider(["# 综述", "# 设计", "# 稿", "评审意见无结构化推荐。"])
        rc = _patched(seq, lambda: run_pipeline(
            topic="X", project_dir=str(proj), auto=True))
        assert rc == 0
        summ = json.loads((proj / "notes" / "pipeline_summary.json")
                          .read_text(encoding="utf-8"))
        assert summ["overall_passed"] is False
        assert summ["review_decision"] == "MAJOR"   # fail-closed


def test_pipeline_no_goal_returns_1():
    with tempfile.TemporaryDirectory() as d:
        rc = _patched(_SeqProvider(["x"]),
                      lambda: run_pipeline(topic=None, project_dir=str(d), auto=True))
        assert rc == 1


# ---------------------------------------------------------------------------
# 自包含 runner(无 pytest 也可跑:python tests/test_pipeline.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"  ✓ {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  ✗ {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ✗ {name}: [ERROR] {type(exc).__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
