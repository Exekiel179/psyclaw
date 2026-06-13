"""预注册模板生成测试(D-2)。

规格:
  - 澄清卡解析是**纯函数**:与 clarify.write_card 的表格格式严格往返,还原转义。
  - 学术诚信:假设按确证/探索归类;未标注 → fail-closed 探索性 + 告警。
  - 样本量依据可复用 D-1 功效分析(power.compute),并保留发表偏倚告警。
  - 缺失关键槽位 → [待补充] 占位 + 告警,绝不替用户编造。
  - 澄清卡缺失 → run_preregister fail-closed 返回 1。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.psych import preregister  # noqa: E402
from psyclaw.psych.clarify import write_card  # noqa: E402
from psyclaw.psych.power import compute  # noqa: E402
from psyclaw.psych.preregister import (  # noqa: E402
    build_prereg, parse_clarification, power_justification_md,
    preregister_cli, render_aspredicted, render_osf, run_preregister,
    split_hypotheses,
)

# 一份较完整的澄清答案(覆盖关键槽位 + 含管道符的内容做转义测试)。
ANSWERS = {
    "research_question": "正念干预能否降低大学生 4 周后的焦虑?",
    "theory_base": "注意控制理论 vs 情绪调节理论",
    "novelty": "首次在中国大学生中检验剂量效应",
    "iv": "正念干预(操纵):干预组 vs 等待组",
    "dv": "GAD-7 量表测焦虑(目标人群 α=.90)",
    "covariates": "基线焦虑(因文献 X 表明与 DV 相关)",
    "population": "目标:大学生;抽样框:某校选修课学生",
    "exclusion": "草率作答 longstring>10 剔除|完成率<80% 剔除",
    "design_type": "被试间两组前后测",
    "randomization": "区组随机,分配隐藏",
    "hypotheses": "H1[确证]:干预组焦虑下降更多;H2[探索]:效果受基线调节;RQ1:性别差异?",
    "effect_expectation": "据元分析 d≈.40",
    "power": "两样本 t,α=.05,功效.80,d=.40 → 每组 100",
    "analysis_plan": "H1 用协方差分析(前测为协变量);前提违反改用稳健回归",
    "ethics": "IRB 已批(编号 2026-001)",
    "prereg": "OSF,数据收集前",
    "data_sharing": "OSF 仓库,匿名化后开放",
}


# ---------------------------------------------------------------------------
# 澄清卡解析(与 clarify.write_card 往返)
# ---------------------------------------------------------------------------

def test_parse_clarification_roundtrip(tmp_path):
    write_card(ANSWERS, tmp_path)
    text = (tmp_path / "notes" / "clarification.md").read_text(encoding="utf-8")
    parsed = parse_clarification(text)
    assert parsed["research_question"] == ANSWERS["research_question"]
    assert parsed["design_type"] == "被试间两组前后测"
    # 含管道符的内容转义还原正确。
    assert parsed["exclusion"] == ANSWERS["exclusion"]
    assert "|" in parsed["exclusion"]


def test_parse_clarification_skips_unresolved(tmp_path):
    partial = {"research_question": "RQ", "dv": ""}  # dv 留空 = 未解决
    write_card(partial, tmp_path)
    text = (tmp_path / "notes" / "clarification.md").read_text(encoding="utf-8")
    parsed = parse_clarification(text)
    assert "research_question" in parsed
    assert "dv" not in parsed                # 未解决不进解析结果


def test_parse_clarification_ignores_header_rows():
    parsed = parse_clarification("| 槽位 | 状态 | 内容 |\n|---|---|---|\n"
                                 "| research_question | resolved | abc |")
    assert parsed == {"research_question": "abc"}


# ---------------------------------------------------------------------------
# 假设切分与确证/探索归类
# ---------------------------------------------------------------------------

def test_split_hypotheses_classifies_confirmatory_exploratory():
    hyps = split_hypotheses(ANSWERS["hypotheses"])
    assert len(hyps) == 3
    by_label = {h["label"]: h for h in hyps}
    assert by_label["H1"]["kind"] == "confirmatory" and by_label["H1"]["tagged"]
    assert by_label["H2"]["kind"] == "exploratory" and by_label["H2"]["tagged"]
    # RQ 前缀自动判为探索性。
    assert by_label["RQ1"]["kind"] == "exploratory" and by_label["RQ1"]["tagged"]
    # 标签与 [确证]/[探索] 标记都从正文里剥掉。
    assert "确证" not in by_label["H1"]["text"]
    assert "H1" not in by_label["H1"]["text"]
    assert by_label["H1"]["text"].startswith("干预组")


def test_split_hypotheses_untagged_is_failclosed_exploratory():
    hyps = split_hypotheses("干预能降低焦虑")
    assert len(hyps) == 1
    assert hyps[0]["kind"] == "exploratory"     # fail-closed
    assert hyps[0]["tagged"] is False           # 标记未显式 → 可被告警


def test_split_hypotheses_empty():
    assert split_hypotheses("") == []
    assert split_hypotheses("   ") == []


def test_split_hypotheses_english_tags():
    hyps = split_hypotheses("H1 [confirmatory]: A predicts B; H2 [exploratory]: C")
    kinds = {h["label"]: h["kind"] for h in hyps}
    assert kinds["H1"] == "confirmatory"
    assert kinds["H2"] == "exploratory"


# ---------------------------------------------------------------------------
# 组装结构化预注册 + 告警
# ---------------------------------------------------------------------------

def test_build_prereg_counts_and_no_warnings_when_complete():
    prereg = build_prereg(ANSWERS)
    assert len(prereg["confirmatory"]) == 1
    assert len(prereg["exploratory"]) == 2
    assert prereg["missing"] == []
    # 关键槽位齐备 + 所有假设已标注 → 无告警。
    assert prereg["warnings"] == []
    assert prereg["title"] == ANSWERS["research_question"]


def test_build_prereg_warns_on_missing_and_untagged():
    partial = {"research_question": "RQ",
               "hypotheses": "干预有效"}      # 未标注 + 缺一堆关键槽位
    prereg = build_prereg(partial)
    assert "dv" in prereg["missing"]
    assert "analysis_plan" in prereg["missing"]
    joined = " ".join(prereg["warnings"])
    assert "未标" in joined                    # 未标注假设告警
    assert "无确证性假设" in joined            # 没有确证假设的告警
    assert any("dv" in w for w in prereg["warnings"])


# ---------------------------------------------------------------------------
# 样本量依据(复用 D-1)
# ---------------------------------------------------------------------------

def test_power_justification_solves_n():
    res = compute("ttest", d=0.5, power=0.80)   # 反解 N
    md = power_justification_md(res)
    assert "所需样本量" in md
    assert "Cohen's d = 0.5" in md
    # 发表偏倚告警必须保留。
    assert any("发表偏倚" in line for line in md.splitlines())


def test_power_justification_given_n():
    res = compute("ttest", d=0.5, n=64)         # 给 N 求功效
    md = power_justification_md(res)
    assert "计划样本量" in md
    assert "功效 =" in md


def test_power_justification_none():
    assert power_justification_md(None) is None
    assert power_justification_md({"error": "x"}) is None


# ---------------------------------------------------------------------------
# 渲染器
# ---------------------------------------------------------------------------

def test_render_osf_has_all_sections_and_hyps():
    prereg = build_prereg(ANSWERS)
    md = render_osf(prereg)
    for section in ("研究信息", "设计计划", "抽样计划", "变量", "分析计划", "其他"):
        assert section in md
    assert "确证性假设" in md and "探索性假设" in md
    assert "干预组焦虑下降更多" in md          # 确证假设正文进文稿
    assert "GAD-7" in md                       # dv
    assert "https://osf.io/prereg" in md


def test_render_osf_placeholders_for_missing():
    prereg = build_prereg({"research_question": "只填了问题"})
    md = render_osf(prereg)
    assert "[待补充：" in md                    # 缺失槽位用占位,不编造
    assert "盲法" in md                         # 模板结构完整


def test_render_aspredicted_eight_questions():
    prereg = build_prereg(ANSWERS)
    md = render_aspredicted(prereg)
    for n in range(1, 9):
        assert f"**{n})" in md                  # 8 问齐全
    assert "aspredicted.org" in md
    assert "题名" in md


def test_render_osf_embeds_power_calc():
    res = compute("ttest", d=0.5, power=0.80)
    prereg = build_prereg(ANSWERS, power_res=res)
    md = render_osf(prereg)
    assert "所需样本量" in md                   # D-1 功效结果嵌入抽样计划


# ---------------------------------------------------------------------------
# 端到端编排(IO)
# ---------------------------------------------------------------------------

def test_run_preregister_missing_card_fail_closed(tmp_path):
    rc = run_preregister(project_dir=tmp_path)
    assert rc == 1                              # 无澄清卡 → fail-closed


def test_run_preregister_writes_both(tmp_path):
    write_card(ANSWERS, tmp_path)
    rc = run_preregister(project_dir=tmp_path)
    assert rc == 0
    assert (tmp_path / "notes" / "preregistration_osf.md").exists()
    assert (tmp_path / "notes" / "preregistration_aspredicted.md").exists()


def test_run_preregister_osf_only(tmp_path):
    write_card(ANSWERS, tmp_path)
    run_preregister(project_dir=tmp_path, fmt="osf")
    assert (tmp_path / "notes" / "preregistration_osf.md").exists()
    assert not (tmp_path / "notes" / "preregistration_aspredicted.md").exists()


def test_run_preregister_embeds_power(tmp_path):
    write_card(ANSWERS, tmp_path)
    run_preregister(project_dir=tmp_path, fmt="osf", test="ttest",
                    power_opts={"d": 0.5, "power": 0.80})
    md = (tmp_path / "notes" / "preregistration_osf.md").read_text(encoding="utf-8")
    assert "所需样本量" in md


def test_preregister_cli_parses_flags(tmp_path, monkeypatch):
    write_card(ANSWERS, tmp_path)
    monkeypatch.chdir(tmp_path)
    rc = preregister_cli(["--osf", "--test", "ttest", "--d", "0.5",
                          "--power-target", "0.8"])
    assert rc == 0
    md = (tmp_path / "notes" / "preregistration_osf.md").read_text(encoding="utf-8")
    assert "所需样本量" in md
    assert not (tmp_path / "notes" / "preregistration_aspredicted.md").exists()


# ---------------------------------------------------------------------------
# 自包含 runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile

    class _TmpPath:
        """极简 tmp_path 替身(无 pytest 时用)。"""

        def __init__(self):
            self._d = Path(tempfile.mkdtemp())

        def __truediv__(self, other):
            return self._d / other

    class _Monkey:
        def chdir(self, p):
            import os
            os.chdir(p if not hasattr(p, "_d") else p._d)

    import inspect
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in fns:
        params = inspect.signature(fn).parameters
        kwargs = {}
        if "tmp_path" in params:
            kwargs["tmp_path"] = _TmpPath()._d
        if "monkeypatch" in params:
            kwargs["monkeypatch"] = _Monkey()
        try:
            fn(**kwargs)
            print(f"  ✓ {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  ✗ {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ✗ {name}: [ERROR] {type(exc).__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
