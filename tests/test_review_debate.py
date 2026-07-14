"""辩论式评审档位(feat-119)—— 独立评审 → 交叉质证 → EIC 综合。

规格:
- run_review(mode=) 两档:`panel`(现状,单次五 persona 生成)/`debate`
  (R1/R2/R3/DA 各自**独立调用**评审 → 每人看到他人意见后交叉质证并给出
  最终推荐 → EIC 独立综合并产出 REQUIRED REVISIONS);
- 每位评审的推荐取自**自己的块**(块内提及其他评审标签不改归属——
  这是单次生成 parse_recommendations 做不到的);
- fail-closed 不变:块内无可解析推荐 → 该评审不计票;无同行 → MAJOR;
  任一 REJECT 不可被平均掉;
- 聚合复用 aggregate_decision,产物文件名不变(review_panel.{md,json}),
  辩论过程另存 notes/review_debate.md;
- 档位选择:mode 参数 > 配置 review_mode > 默认 panel;CLI --debate。

运行:python -m pytest tests/test_review_debate.py 或直接 python 本文件。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw import review as review_mod  # noqa: E402
from psyclaw.review import (  # noqa: E402
    DEBATE_PERSONAS,
    debate_summary,
    last_recommendation,
    review_cli,
    run_review,
)


# ---------------------------------------------------------------------------
# 纯函数:last_recommendation
# ---------------------------------------------------------------------------

def test_last_recommendation_none_is_empty():
    assert last_recommendation("没有推荐行的普通文本") == ""
    assert last_recommendation("") == ""


def test_last_recommendation_takes_last_parseable():
    text = ("初步判断:\nRECOMMENDATION: MAJOR\n"
            "交叉质证后修正:\nRECOMMENDATION: MINOR\n")
    assert last_recommendation(text) == "MINOR"


def test_last_recommendation_skips_unparseable_token():
    # 末行 token 无法归一 → 回落到上一个可归一推荐(fail-closed 不猜)。
    text = "RECOMMENDATION: REJECT\nRECOMMENDATION: MAYBE\n"
    assert last_recommendation(text) == "REJECT"


# ---------------------------------------------------------------------------
# 纯函数:debate_summary(推荐归属自己的块,不受块内他人标签影响)
# ---------------------------------------------------------------------------

_EIC_TEXT = """\
综合四方意见:方法学问题必须先修。
RECOMMENDATION: MAJOR

## REQUIRED REVISIONS
- [ ] [BLOCKING] 报告效应量与 95% CI
- [ ] [MINOR] 统一术语
"""


def test_debate_summary_attributes_rec_to_own_block():
    # R1 块里提到 R2,推荐仍必须归 R1(单次生成的逐行解析做不到这一点)。
    blocks = {
        "R1": "我不同意 R2 的乐观判断,混淆变量未控制。\nRECOMMENDATION: REJECT\n",
        "R2": "理论定位充分。\nRECOMMENDATION: ACCEPT\n",
        "R3": "数据代码已公开。\nRECOMMENDATION: ACCEPT\n",
    }
    s = debate_summary(blocks, _EIC_TEXT)
    by = {r["reviewer"]: r["recommendation"] for r in s["recommendations"]}
    assert by["R1"] == "REJECT" and by["R2"] == "ACCEPT" and by["R3"] == "ACCEPT"


def test_debate_summary_reject_cannot_be_averaged():
    blocks = {
        "R1": "RECOMMENDATION: ACCEPT",
        "R2": "RECOMMENDATION: ACCEPT",
        "R3": "RECOMMENDATION: ACCEPT",
        "DA": "存在能推翻结论的替代解释。\nRECOMMENDATION: REJECT",
    }
    s = debate_summary(blocks, "RECOMMENDATION: ACCEPT\n## REQUIRED REVISIONS\n")
    # DA 不计票,但其 REJECT 把决定托底到至少 MAJOR(致命缺陷不可被平均掉)。
    assert s["decision"] == "MAJOR" and s["passed"] is False


def test_debate_summary_fail_closed_without_parseable_recs():
    blocks = {"R1": "只有叙述没有推荐行", "R2": "同上"}
    s = debate_summary(blocks, "也没有推荐")
    assert s["decision"] == "MAJOR" and s["passed"] is False
    assert s["n_peer_reviews"] == 0


def test_debate_summary_extracts_eic_action_items():
    blocks = {"R1": "RECOMMENDATION: MAJOR"}
    s = debate_summary(blocks, _EIC_TEXT)
    assert s["n_blocking"] == 1 and s["n_minor"] == 1


# ---------------------------------------------------------------------------
# 编排:run_review(mode="debate") 端到端(stub provider)
# ---------------------------------------------------------------------------

class _SeqProvider:
    name = "seq"

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls: list[str] = []

    def chat(self, messages, system=""):
        self.calls.append(messages[-1]["content"])
        yield self.outputs.pop(0) if self.outputs else "RECOMMENDATION: MAJOR"


def _patched(provider, conf, fn):
    import psyclaw.providers as prov
    from psyclaw import config as cfg
    orig_gp, orig_lc = prov.get_provider, cfg.load_config
    prov.get_provider = lambda c: provider
    cfg.load_config = lambda: conf
    try:
        return fn()
    finally:
        prov.get_provider, cfg.load_config = orig_gp, orig_lc


_CONF = {"provider": "mock", "model": "default", "base_url": ""}

# 独立阶段 4 份意见 + 质证阶段 4 份最终意见 + EIC 综合 = 9 次调用。
_DEBATE_SEQ = (
    ["初评。\nRECOMMENDATION: MINOR"] * 4
    + ["质证后维持/修正。\nRECOMMENDATION: ACCEPT"] * 3      # R1/R2/R3 最终
    + ["压力测试:仍有小疑虑。\nRECOMMENDATION: MINOR"]        # DA 最终
    + ["综合:可接收。\nRECOMMENDATION: ACCEPT\n## REQUIRED REVISIONS\n"]  # EIC
)


def _run_debate(tmp: str, seq=None, **kw):
    proj = Path(tmp)
    draft = proj / "draft.md"
    draft.write_text("# 稿件\n效应量 d=0.5, 95% CI [0.2, 0.8]。", encoding="utf-8")
    provider = _SeqProvider(seq or list(_DEBATE_SEQ))
    rc = _patched(provider, dict(_CONF, **kw.pop("conf", {})),
                  lambda: run_review(draft=str(draft), project_dir=tmp, **kw))
    return rc, provider, proj


def test_run_review_debate_runs_nine_calls_and_passes():
    with tempfile.TemporaryDirectory() as d:
        rc, provider, proj = _run_debate(d, mode="debate")
        assert rc == 0
        assert len(provider.calls) == 1 + 2 * len(DEBATE_PERSONAS)  # 4+4+1=9
        data = json.loads((proj / "notes" / "review_panel.json")
                          .read_text(encoding="utf-8"))
        assert data["decision"] == "ACCEPT" and data["passed"] is True
        assert data["n_peer_reviews"] == 3
        assert data["mode"] == "debate"


def test_run_review_debate_writes_transcript_and_panel():
    with tempfile.TemporaryDirectory() as d:
        rc, _, proj = _run_debate(d, mode="debate")
        assert rc == 0
        panel = (proj / "notes" / "review_panel.md").read_text(encoding="utf-8")
        for label, _desc in DEBATE_PERSONAS:
            assert label in panel
        assert "EIC" in panel
        debate = (proj / "notes" / "review_debate.md").read_text(encoding="utf-8")
        assert "独立" in debate and "质证" in debate


def test_run_review_debate_rebuttal_sees_others_opinions():
    with tempfile.TemporaryDirectory() as d:
        _, provider, _ = _run_debate(d, mode="debate")
        n = len(DEBATE_PERSONAS)
        rebuttals = provider.calls[n:2 * n]
        assert all("其他评审" in c for c in rebuttals)
        # EIC 综合看到的是质证后的最终意见。
        assert "质证" in provider.calls[-1]


def test_run_review_mode_defaults_from_config():
    with tempfile.TemporaryDirectory() as d:
        _, provider, _ = _run_debate(d, conf={"review_mode": "debate"})
        assert len(provider.calls) == 9


def test_run_review_default_stays_single_panel():
    with tempfile.TemporaryDirectory() as d:
        rc, provider, _ = _run_debate(d, seq=["### R1\nRECOMMENDATION: ACCEPT\n"
                                              "## REQUIRED REVISIONS\n"])
        assert rc == 0
        assert len(provider.calls) == 1        # 快评档不涨成本


def test_review_cli_parses_debate_flag(monkeypatch):
    seen = {}

    def fake_run_review(**kw):
        seen.update(kw)
        return 0

    monkeypatch.setattr(review_mod, "run_review", fake_run_review)
    assert review_cli(["draft.md", "--debate"]) == 0
    assert seen["mode"] == "debate"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
