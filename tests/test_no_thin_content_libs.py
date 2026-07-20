"""发行包不得再内置「半吊子内容库」(feat-186)。

决定与理由:内置量表只有 7 条(dass/phq/gad/tipi/rses/pss)、实验设计只有 12 类,
用户做倦怠研究搜 MBI、或输入真实研究问题,得到的都是「未收录」——这种覆盖不是
帮忙而是帮倒忙,还让人误以为库里查过了。与既有的「统计外移」「方法学背书库已删」
同一原则:**宁可不内置,也不做半吊子内容库**。

保留的是**机器**:计分(反向计分/分量表求和/缺失处理)、信度、伦理提示、
质量检查判据——它们由用户在 `.psyclaw/scales/*.yaml` 定义的量表驱动,覆盖无上限。

预注册同理:`preregister` 命令删除(模板模型本就会写),但 gates 的
`DESIGN.prereg` 质量检查**保留**——「确证性研究须预注册或标注探索性」是学术
诚信红线,`CLAUDE.md` 明写质量检查只增不删。
"""
from __future__ import annotations

from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "psyclaw"


def test_no_builtin_scale_library_shipped():
    assert not (PKG / "psych" / "scales.yaml").exists()
    assert not (PKG / "psych" / "cn_norms.json").exists()


def test_no_builtin_design_library_shipped():
    assert not (PKG / "psych" / "designs.json").exists()


def test_preregister_module_removed():
    assert not (PKG / "psych" / "preregister.py").exists()


def test_scoring_machinery_kept():
    """机器要留下——删的是内容,不是能力。"""
    from psyclaw.psych.scales import get_scale, list_scales, score_datafile  # noqa: F401


def test_user_defined_scales_still_drive_everything(tmp_path):
    """用户自定义量表仍能驱动计分:覆盖面由用户决定,不再受内置 7 条限制。"""
    from psyclaw.psych import scales
    d = tmp_path / ".psyclaw" / "scales"
    d.mkdir(parents=True)
    (d / "mbi.yaml").write_text(
        "- id: mbi-demo\n"
        "  name: 简版倦怠量表\n"
        "  items: 3\n"
        "  scale_min: 1\n"
        "  scale_max: 5\n"
        "  reverse: [3]\n",
        encoding="utf-8")
    got = scales.get_scale("mbi-demo", project_dir=tmp_path)
    assert got and got["name"] == "简版倦怠量表"
    assert 3 in (got.get("reverse") or [])


def test_prereg_quality_check_still_enforced():
    """预注册命令删了,但「确证须预注册或标探索」的质量检查不许删(学术诚信红线)。"""
    rules = (PKG / "gates" / "rules.yaml").read_text(encoding="utf-8")
    assert "preregistration" in rules and "exploratory_label" in rules
