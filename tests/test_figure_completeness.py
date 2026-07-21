"""图件完整性门(feat-194)。

真实事故(用户实测,outputs/nhb_manuscript.md):一篇 Nature Human Behaviour 稿的
主路径图从没生成,交付稿里赫然留着 `![Path diagram — to be generated](…png)`;
次要 moderation 图生成了却① 没内嵌、② 存到 figures/ 而链接指向 outputs/figures/
成孤儿。质检(JARS + 诚信启发式)此前完全不看图,全过、静默交付——正是
「缺内容 + 可视化不够」的来源。

图是论文内容的一部分,不是可选项:
  - 占位未兑现(alt 自认 to be generated / 待生成 / 占位)→ block;
  - 图片链接指向不存在的文件(需草稿目录)→ block。
"""
from __future__ import annotations

from psyclaw.output.jars import (
    check_draft,
    figure_file_flags,
    integrity_flags,
)

# JARS 全项齐备、无诚信越界的干净底稿——用于隔离「图件」信号(不被其他 block 干扰)。
_BASE = """
# 方法

## 被试

纳入标准为 18–65 岁成年人,排除标准包括 DSM-5 轴一诊断。
功效分析(G*Power)基于先验 d = 0.40、α = .05、power = .80,每组 N = 100。

## 程序

共排除了 12 名被试(草率作答),剔除标准与预注册一致。
缺失数据采用 FIML 处理。

## 测量

量表 Cronbach α = .78,内部一致性良好。

## 结果

主效应显著,Cohen's d = 0.42,95% CI [0.20, 0.64];Bonferroni 校正用于多重比较。
"""


def _ids(flags):
    return [f["id"] for f in flags]


# --------------------------------------------------------------------------
# 占位未兑现(文本级,不需目录)
# --------------------------------------------------------------------------

def test_placeholder_alt_english_blocks():
    """![… to be generated](…) —— 就是那份 NHB 稿的原样占位。"""
    text = _BASE + "\n![Path diagram — to be generated](figures/path.png)\n"
    flags = integrity_flags(text)
    assert "I.figure_placeholder" in _ids(flags)
    assert any(f["severity"] == "block" for f in flags
               if f["id"] == "I.figure_placeholder")


def test_placeholder_alt_chinese_blocks():
    text = _BASE + "\n![路径图:待生成](figures/path.png)\n"
    assert "I.figure_placeholder" in _ids(integrity_flags(text))


def test_placeholder_fails_check_draft():
    text = _BASE + "\n![Figure 1 — will be inserted](figures/f1.png)\n"
    r = check_draft(text, "quant")
    assert r["passed"] is False
    assert r["n_integrity_block"] >= 1


def test_body_text_mentioning_placeholder_not_flagged():
    """正文谈论「占位符」的行文不该被误伤——只扫 ![](…) 的 alt。"""
    text = _BASE + "\n我们在问卷中使用占位符文本作为注意力检测题。\n"
    assert "I.figure_placeholder" not in _ids(integrity_flags(text))


def test_real_figure_caption_without_placeholder_passes():
    text = _BASE + "\n![Path model of burnout mediating autonomy and turnover](f.png)\n"
    assert "I.figure_placeholder" not in _ids(integrity_flags(text))


# --------------------------------------------------------------------------
# 断链(文件级,需草稿目录)
# --------------------------------------------------------------------------

def test_missing_file_blocks(tmp_path):
    text = _BASE + "\n![Path diagram](figures/nhb_path_diagram.png)\n"
    flags = figure_file_flags(text, tmp_path)          # 该 png 不存在
    assert "I.figure_missing_file" in _ids(flags)
    assert flags[0]["severity"] == "block"


def test_existing_file_passes(tmp_path):
    (tmp_path / "figures").mkdir()
    (tmp_path / "figures" / "ok.png").write_bytes(b"\x89PNG\r\n")
    text = _BASE + "\n![Path diagram](figures/ok.png)\n"
    assert figure_file_flags(text, tmp_path) == []


def test_remote_and_datauri_skipped(tmp_path):
    text = (_BASE
            + "\n![remote](https://example.org/a.png)\n"
            + "\n![inline](data:image/png;base64,iVBOR)\n")
    assert figure_file_flags(text, tmp_path) == []


def test_image_with_title_part_resolved(tmp_path):
    """![](a.png \"标题\") 的 title 部分不参与路径解析。"""
    (tmp_path / "a.png").write_bytes(b"\x89PNG")
    text = _BASE + "\n![x](a.png \"An informative caption\")\n"
    assert figure_file_flags(text, tmp_path) == []


def test_check_draft_with_base_dir_flags_missing(tmp_path):
    draft = _BASE + "\n![Path diagram](figures/missing.png)\n"
    r = check_draft(draft, "quant", base_dir=tmp_path)
    assert r["passed"] is False
    assert "I.figure_missing_file" in _ids(r["integrity"])


def test_check_draft_without_base_dir_skips_file_check(tmp_path):
    """不传 base_dir → 行为与旧签名一致,不做文件级校验。"""
    draft = _BASE + "\n![Path diagram](figures/missing.png)\n"
    r = check_draft(draft, "quant")               # 无 base_dir
    assert "I.figure_missing_file" not in _ids(r["integrity"])


def test_references_section_images_not_file_checked(tmp_path):
    """参考文献区之后的内容不扫(与 integrity 同口径),避免误伤。"""
    draft = (_BASE
             + "\n## 参考文献\n\n![logo](refs/publisher_logo.png)\n")
    assert figure_file_flags(draft, tmp_path) == []
