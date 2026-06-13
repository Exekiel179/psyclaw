"""审稿模拟红队测试 —— 评审解析与编辑决定是 fail-closed 的产品规格。

运行:python -m pytest tests/ 或 python tests/test_review.py
原则:解析不到同行推荐 → 不予接收(保守);致命缺陷(任一评审 REJECT)
不可被平均成 ACCEPT/MINOR;BLOCKING 行动项必须被抽出以驱动修复环。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw import review  # noqa: E402
from psyclaw.review import (  # noqa: E402
    aggregate_decision,
    blocking_items,
    extract_action_items,
    parse_recommendations,
    response_letter_skeleton,
    run_review,
    summarize,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

PANEL_MAJOR = """\
### R1 方法学
问题:未报告效应量与置信区间。
RECOMMENDATION: MAJOR

### R2 理论
新意尚可。
RECOMMENDATION: MINOR

### R3 可复现性
数据与代码未公开。
RECOMMENDATION: MAJOR

### DA Devil's Advocate
存在未控制的混淆变量,结论可被替代解释推翻。
RECOMMENDATION: REJECT

### EIC 主编
综合各方,需大修。
RECOMMENDATION: MAJOR
EDITORIAL DECISION: Major Revision

## REQUIRED REVISIONS
- [ ] [BLOCKING] 报告效应量与 95% CI
- [ ] [MAJOR] 增补先验功效分析
- [ ] [MINOR] 统一术语
- [x] [MINOR] 修正图注
- [ ] 公开数据与代码
"""

PANEL_ACCEPT = """\
### R1
扎实。
RECOMMENDATION: ACCEPT

### R2
RECOMMENDATION: ACCEPT

### R3
RECOMMENDATION: ACCEPT

## REQUIRED REVISIONS
- [ ] [MINOR] 个别错字
"""


class _SeqProvider:
    """按调用顺序吐出预设文本的 stub provider(整段一次性 yield)。"""

    name = "seq"

    def __init__(self, outs: list[str]) -> None:
        self._outs = list(outs)
        self._i = 0

    def chat(self, messages: list, system: str = ""):
        out = self._outs[min(self._i, len(self._outs) - 1)]
        self._i += 1
        yield out


# ---------------------------------------------------------------------------
# parse_recommendations
# ---------------------------------------------------------------------------

def test_parse_recommendations_labels_and_peer_flag():
    recs = parse_recommendations(PANEL_MAJOR)
    by = {r["reviewer"]: r for r in recs}
    assert by["R1"]["recommendation"] == "MAJOR" and by["R1"]["is_peer"]
    assert by["R2"]["recommendation"] == "MINOR" and by["R2"]["is_peer"]
    assert by["R3"]["recommendation"] == "MAJOR" and by["R3"]["is_peer"]
    assert by["DA"]["recommendation"] == "REJECT" and not by["DA"]["is_peer"]
    assert by["EIC"]["recommendation"] == "MAJOR" and not by["EIC"]["is_peer"]


def test_parse_normalizes_revision_suffix():
    recs = parse_recommendations("### R1\nRECOMMENDATION: Major Revision")
    assert recs[0]["recommendation"] == "MAJOR"
    recs2 = parse_recommendations("### R1\nrecommendation:minor revision")
    assert recs2[0]["recommendation"] == "MINOR"


def test_parse_skips_unrecognized_token():
    # 无法归一的推荐 token 跳过(fail-closed:不错认为 ACCEPT)。
    recs = parse_recommendations("### R1\nRECOMMENDATION: 待定")
    assert recs == []


# ---------------------------------------------------------------------------
# aggregate_decision —— 保守 / fail-closed
# ---------------------------------------------------------------------------

def test_decision_all_accept():
    recs = [{"reviewer": f"R{i}", "recommendation": "ACCEPT", "is_peer": True}
            for i in (1, 2, 3)]
    assert aggregate_decision(recs) == "ACCEPT"


def test_decision_no_peer_is_failclosed_major():
    # 只有 EIC/DA、没有同行推荐 → 不予接收。
    recs = [{"reviewer": "EIC", "recommendation": "ACCEPT", "is_peer": False},
            {"reviewer": "DA", "recommendation": "ACCEPT", "is_peer": False}]
    assert aggregate_decision(recs) == "MAJOR"
    assert aggregate_decision([]) == "MAJOR"


def test_decision_two_peer_reject_is_reject():
    recs = [{"reviewer": "R1", "recommendation": "REJECT", "is_peer": True},
            {"reviewer": "R2", "recommendation": "REJECT", "is_peer": True},
            {"reviewer": "R3", "recommendation": "MINOR", "is_peer": True}]
    assert aggregate_decision(recs) == "REJECT"


def test_decision_da_reject_cannot_be_averaged_away():
    # 同行全 ACCEPT(均值 0)但 DA 判 REJECT → 致命缺陷不可被平均掉,至少 MAJOR。
    recs = [{"reviewer": f"R{i}", "recommendation": "ACCEPT", "is_peer": True}
            for i in (1, 2, 3)]
    recs.append({"reviewer": "DA", "recommendation": "REJECT", "is_peer": False})
    assert aggregate_decision(recs) == "MAJOR"


def test_decision_single_peer_reject_overrides_to_major():
    # 单个同行 REJECT(未达 2 票)+ 两个 ACCEPT:均值映射 MINOR,但 REJECT 触发上调 MAJOR。
    recs = [{"reviewer": "R1", "recommendation": "REJECT", "is_peer": True},
            {"reviewer": "R2", "recommendation": "ACCEPT", "is_peer": True},
            {"reviewer": "R3", "recommendation": "ACCEPT", "is_peer": True}]
    assert aggregate_decision(recs) == "MAJOR"


def test_decision_minor_band():
    recs = [{"reviewer": "R1", "recommendation": "MINOR", "is_peer": True},
            {"reviewer": "R2", "recommendation": "MINOR", "is_peer": True},
            {"reviewer": "R3", "recommendation": "ACCEPT", "is_peer": True}]
    # 均值 (1+1+0)/3 = .67 → MINOR,无 REJECT 不上调。
    assert aggregate_decision(recs) == "MINOR"


# ---------------------------------------------------------------------------
# extract_action_items
# ---------------------------------------------------------------------------

def test_extract_action_items_severity_and_done():
    items = extract_action_items(PANEL_MAJOR)
    assert len(items) == 5
    sev = [i["severity"] for i in items]
    assert sev.count("BLOCKING") == 1
    assert sev.count("MAJOR") == 2          # 含 1 条未标注 → 默认 MAJOR
    assert sev.count("MINOR") == 2
    done = [i for i in items if i["done"]]
    assert len(done) == 1 and done[0]["severity"] == "MINOR"


def test_extract_untagged_defaults_major():
    items = extract_action_items(PANEL_MAJOR)
    untagged = [i for i in items if i["text"] == "公开数据与代码"]
    assert untagged and untagged[0]["severity"] == "MAJOR"


def test_extract_fallback_scan_without_section():
    text = "随便几行\n- [ ] [BLOCKING] 修复致命问题\n- 普通项不带标签不计入"
    items = extract_action_items(text)
    assert len(items) == 1 and items[0]["severity"] == "BLOCKING"


def test_blocking_items_filter():
    items = extract_action_items(PANEL_MAJOR)
    blk = blocking_items(items)
    assert len(blk) == 1 and blk[0]["text"] == "报告效应量与 95% CI"


# ---------------------------------------------------------------------------
# summarize / response_letter
# ---------------------------------------------------------------------------

def test_summarize_major_panel():
    s = summarize(PANEL_MAJOR)
    assert s["decision"] == "MAJOR" and s["passed"] is False
    assert s["n_peer_reviews"] == 3
    assert s["n_blocking"] == 1 and s["n_major"] == 2 and s["n_minor"] == 2


def test_summarize_accept_panel():
    s = summarize(PANEL_ACCEPT)
    assert s["decision"] == "ACCEPT" and s["passed"] is True


def test_response_letter_orders_by_severity():
    letter = response_letter_skeleton(extract_action_items(PANEL_MAJOR))
    i_block = letter.index("[BLOCKING]")
    i_major = letter.index("[MAJOR]")
    i_minor = letter.index("[MINOR]")
    assert i_block < i_major < i_minor       # 致命项排最前
    assert "待填写" in letter                  # 留给人工填写


# ---------------------------------------------------------------------------
# run_review 端到端(stub provider,不依赖真实 LLM)
# ---------------------------------------------------------------------------

def _patched(provider, fn):
    """临时把 psyclaw.providers.get_provider 换成返回 provider 的桩。"""
    import psyclaw.providers as prov
    orig = prov.get_provider
    prov.get_provider = lambda conf: provider
    try:
        return fn()
    finally:
        prov.get_provider = orig


def test_run_review_plain_writes_artifacts():
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        (proj / "outputs").mkdir(parents=True)
        draft = proj / "outputs" / "report.md"
        draft.write_text("# 一篇稿件\n结果显著。", encoding="utf-8")
        rc = _patched(_SeqProvider([PANEL_MAJOR]),
                      lambda: run_review(draft=str(draft), project_dir=str(proj)))
        assert rc == 0
        panel = proj / "notes" / "review_panel.md"
        js = proj / "notes" / "review_panel.json"
        letter = proj / "notes" / "response_letter.md"
        assert panel.exists() and js.exists() and letter.exists()
        data = json.loads(js.read_text(encoding="utf-8"))
        assert data["decision"] == "MAJOR"
        assert data["n_blocking"] == 1


def test_run_review_revise_converges_to_accept():
    # round1 MAJOR → executor 修订 → round2 ACCEPT;修复环应收敛并返回 0。
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        draft = proj / "draft.md"
        draft.write_text("# 初稿\n未报告效应量。", encoding="utf-8")
        seq = _SeqProvider([PANEL_MAJOR, "# 修订稿\n已补效应量与 CI。", PANEL_ACCEPT])
        rc = _patched(seq, lambda: run_review(
            draft=str(draft), project_dir=str(proj), revise=True, auto=True, rounds=3))
        assert rc == 0
        data = json.loads((proj / "notes" / "review_panel.json")
                          .read_text(encoding="utf-8"))
        assert data["decision"] == "ACCEPT" and data["passed"] is True
        assert (proj / "notes" / "revised_draft.md").exists()


def test_run_review_revise_non_convergence_returns_1():
    # 始终 MAJOR,达最大轮次仍未 ACCEPT → 返回 1(与 run_loop 修复环不收敛即停一致)。
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        draft = proj / "draft.md"
        draft.write_text("# 初稿", encoding="utf-8")
        seq = _SeqProvider([PANEL_MAJOR, "# 修订", PANEL_MAJOR, "# 修订2", PANEL_MAJOR])
        rc = _patched(seq, lambda: run_review(
            draft=str(draft), project_dir=str(proj), revise=True, auto=True, rounds=2))
        assert rc == 1


def test_run_review_missing_draft_returns_1():
    with tempfile.TemporaryDirectory() as d:
        rc = _patched(_SeqProvider([PANEL_ACCEPT]),
                      lambda: run_review(draft=None, project_dir=str(d)))
        assert rc == 1


# ---------------------------------------------------------------------------
# 自包含 runner(无 pytest 也可跑:python tests/test_review.py)
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
