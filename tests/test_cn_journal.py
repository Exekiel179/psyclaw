"""W-3: 中文心理学语境 — cn_journal.py + cn_norms.json 测试。"""

import json
import sys
from pathlib import Path

try:
    import pytest
    _approx = pytest.approx
except ImportError:
    pytest = None  # type: ignore[assignment]
    def _approx(val, rel=1e-3):  # type: ignore[misc]
        class _A:
            def __eq__(self, other): return abs(other - val) <= abs(val) * rel + 1e-9
        return _A()

# 确保包可以导入
sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.output.cn_journal import (
    JOURNALS,
    CnJournalDocument,
    convert_apa_ref_to_cn,
    convert_to_cn_format,
    format_bilingual_abstract,
    format_cn_reference,
    format_cn_stat_md,
    get_journal_spec,
    list_journals,
)
from psyclaw.psych.scales import (
    format_cn_norms_text,
    get_cn_norms,
    print_cn_norms,
)


# ---------------------------------------------------------------------------
# list_journals / get_journal_spec
# ---------------------------------------------------------------------------

class TestListJournals:
    def test_returns_three_journals(self):
        jmap = list_journals()
        assert "apa7" in jmap
        assert "xinlixuebao" in jmap
        assert "xinlikexue" in jmap

    def test_labels_are_strings(self):
        for jid, label in list_journals().items():
            assert isinstance(label, str) and label

    def test_unknown_falls_back_to_apa7(self):
        spec = get_journal_spec("nonexistent")
        assert spec is JOURNALS["apa7"]

    def test_xinlixuebao_is_bilingual(self):
        spec = get_journal_spec("xinlixuebao")
        assert "zh" in spec["abstract_lang"]
        assert "en" in spec["abstract_lang"]

    def test_xinlikexue_citation_style(self):
        spec = get_journal_spec("xinlikexue")
        assert spec["citation_style"] == "gbt7714"

    def test_apa7_citation_style(self):
        spec = get_journal_spec("apa7")
        assert spec["citation_style"] == "apa"


# ---------------------------------------------------------------------------
# format_bilingual_abstract
# ---------------------------------------------------------------------------

class TestFormatBilingualAbstract:
    def test_contains_cn_abstract(self):
        out = format_bilingual_abstract("中文摘要内容", "English abstract.", journal="xinlixuebao")
        assert "中文摘要内容" in out

    def test_contains_en_abstract(self):
        out = format_bilingual_abstract("中文摘要", "English abstract.", journal="xinlixuebao")
        assert "English abstract." in out

    def test_cn_section_header(self):
        out = format_bilingual_abstract("摘要内容", "Abstract text.", journal="xinlixuebao")
        assert "摘" in out  # 摘要 or 摘  要

    def test_en_section_header(self):
        out = format_bilingual_abstract("摘要内容", "Abstract text.", journal="xinlixuebao")
        assert "Abstract" in out

    def test_cn_keywords_included(self):
        out = format_bilingual_abstract(
            "摘要", "Abstract",
            cn_keywords=["情绪调节", "认知重评"],
            journal="xinlixuebao",
        )
        assert "情绪调节" in out
        assert "认知重评" in out

    def test_en_keywords_included(self):
        out = format_bilingual_abstract(
            "摘要", "Abstract",
            en_keywords=["emotion regulation", "cognitive reappraisal"],
            journal="xinlixuebao",
        )
        assert "emotion regulation" in out

    def test_xinlikexue_journal(self):
        out = format_bilingual_abstract("摘要", "Abstract", journal="xinlikexue")
        assert "摘" in out
        assert "Abstract" in out

    def test_cn_only_no_crash(self):
        out = format_bilingual_abstract("仅中文", "", journal="xinlixuebao")
        assert "仅中文" in out

    def test_en_only_no_crash(self):
        out = format_bilingual_abstract("", "English only.", journal="xinlixuebao")
        assert "English only." in out


# ---------------------------------------------------------------------------
# format_cn_reference
# ---------------------------------------------------------------------------

class TestFormatCnReference:
    def test_basic_format(self):
        ref = format_cn_reference(
            authors="张三, 李四",
            year=2023,
            title="情绪调节与心理健康",
            journal="心理学报",
            volume="55",
            issue="3",
            pages="456-470",
        )
        assert "[J]" in ref
        assert "张三" in ref
        assert "心理学报" in ref
        assert "2023" in ref
        assert "55(3)" in ref
        assert "456-470" in ref

    def test_with_doi(self):
        ref = format_cn_reference(
            authors="Wang, K.",
            year=2022,
            title="Test Scale",
            journal="Acta Psychologica Sinica",
            doi="10.3724/test.001",
        )
        assert "10.3724/test.001" in ref or "doi.org" in ref

    def test_without_volume_issue(self):
        ref = format_cn_reference("李明", 2020, "研究标题", "心理科学")
        assert "李明" in ref
        assert "2020" in ref

    def test_ends_with_period(self):
        ref = format_cn_reference("Author", 2021, "Title", "Journal", volume="10")
        assert "." in ref[-5:]  # ends with period (or doi after period)

    def test_issue_without_volume(self):
        ref = format_cn_reference("A", 2020, "T", "J", volume="", issue="2", pages="1-5")
        assert "(2)" in ref


# ---------------------------------------------------------------------------
# convert_apa_ref_to_cn
# ---------------------------------------------------------------------------

class TestConvertApaRefToCn:
    def test_standard_apa_article(self):
        apa = "Smith, J. A. (2021). Emotion regulation in adults. Journal of Psychology, 45(2), 123-145."
        cn = convert_apa_ref_to_cn(apa)
        assert "[J]" in cn
        assert "2021" in cn
        assert "Journal of Psychology" in cn

    def test_unrecognized_ref_returned_as_is(self):
        weird = "Some non-standard reference text here"
        assert convert_apa_ref_to_cn(weird) == weird

    def test_preserves_doi_in_output(self):
        apa = "Brown, T. (2022). Study title. Psych Review, 30(1), 1-20. https://doi.org/10.1000/test"
        cn = convert_apa_ref_to_cn(apa)
        assert "10.1000/test" in cn


# ---------------------------------------------------------------------------
# format_cn_stat_md
# ---------------------------------------------------------------------------

class TestFormatCnStatMd:
    def test_t_stat_italicized(self):
        out = format_cn_stat_md("t(28) = 3.21, p < .001")
        assert "*t*" in out
        assert "*p*" in out

    def test_effect_size_italicized(self):
        out = format_cn_stat_md("Cohen's d = 0.45")
        assert "*d*" in out

    def test_f_stat_italicized(self):
        out = format_cn_stat_md("F(2, 97) = 5.43, p = .006, η² = .10")
        assert "*F*" in out
        assert "*η*" in out


# ---------------------------------------------------------------------------
# convert_to_cn_format
# ---------------------------------------------------------------------------

class TestConvertToCnFormat:
    _sample_apa_md = """---
title: Test Study
---

# Test Study

## Abstract

This is the abstract.

## Introduction

Introduction text.

## Method

Method text.

## Results

Results text.

## Discussion

Discussion text.

## References

Smith, J. A. (2021). Emotion study. Journal of Emotion, 10(1), 1-15.
"""

    def test_references_header_converted(self):
        out = convert_to_cn_format(self._sample_apa_md, "xinlixuebao")
        assert "参考文献" in out

    def test_method_header_converted(self):
        out = convert_to_cn_format(self._sample_apa_md, "xinlixuebao")
        assert "研究方法" in out or "方" in out

    def test_results_header_converted(self):
        out = convert_to_cn_format(self._sample_apa_md, "xinlixuebao")
        assert "结  果" in out or "结果" in out

    def test_discussion_header_converted(self):
        out = convert_to_cn_format(self._sample_apa_md, "xinlixuebao")
        assert "讨  论" in out or "讨论" in out

    def test_apa7_passthrough(self):
        out = convert_to_cn_format(self._sample_apa_md, "apa7")
        assert out == self._sample_apa_md

    def test_ref_converted_to_gbt(self):
        out = convert_to_cn_format(self._sample_apa_md, "xinlixuebao")
        assert "[J]" in out


# ---------------------------------------------------------------------------
# CnJournalDocument
# ---------------------------------------------------------------------------

class TestCnJournalDocument:
    def _make_doc(self, journal="xinlixuebao"):
        doc = CnJournalDocument(
            title="Cognitive Reappraisal and Depression",
            cn_title="认知重评与抑郁的关系研究",
            authors="Li, M., Wang, K.",
            cn_authors="李明, 王凯",
            affiliation="Beijing Normal University",
            journal_id=journal,
        )
        doc.set_abstract("The abstract in English.", keywords=["reappraisal", "depression"])
        doc.set_cn_abstract("中文摘要内容。", keywords=["认知重评", "抑郁"])
        doc.add_heading("Introduction", 1)
        doc.add_paragraph("This is the introduction paragraph.")
        doc.add_heading("Method", 1)
        doc.add_paragraph("Participants were recruited.")
        doc.add_reference("Smith, J. A. (2021). A study. Psych Review, 10(2), 1-10.")
        return doc

    def test_cn_title_in_markdown(self):
        doc = self._make_doc()
        md = doc.to_markdown()
        assert "认知重评与抑郁" in md

    def test_en_title_in_markdown(self):
        doc = self._make_doc()
        md = doc.to_markdown()
        assert "Cognitive Reappraisal" in md

    def test_cn_abstract_in_markdown(self):
        doc = self._make_doc()
        md = doc.to_markdown()
        assert "中文摘要内容" in md

    def test_en_abstract_in_markdown(self):
        doc = self._make_doc()
        md = doc.to_markdown()
        assert "The abstract in English." in md

    def test_cn_keywords_in_markdown(self):
        doc = self._make_doc()
        md = doc.to_markdown()
        assert "认知重评" in md
        assert "抑郁" in md

    def test_cn_ref_header(self):
        doc = self._make_doc()
        md = doc.to_markdown()
        assert "参考文献" in md

    def test_en_ref_header_in_apa7_mode(self):
        doc = self._make_doc(journal="apa7")
        md = doc.to_markdown()
        assert "References" in md

    def test_cn_section_labels_applied(self):
        doc = self._make_doc()
        md = doc.to_markdown()
        assert "引  言" in md or "研究方法" in md or "引言" in md

    def test_journal_spec_in_frontmatter(self):
        doc = self._make_doc()
        md = doc.to_markdown()
        assert "心理学报" in md or "Acta Psychologica" in md

    def test_xinlikexue_journal(self):
        doc = self._make_doc(journal="xinlikexue")
        md = doc.to_markdown()
        assert "心理科学" in md or "Psychological Science" in md

    def test_set_cn_abstract_strips_whitespace(self):
        doc = CnJournalDocument()
        doc.set_cn_abstract("  摘要  ", keywords=["k1"])
        assert doc.cn_abstract == "摘要"

    def test_references_converted_in_cn_mode(self):
        doc = self._make_doc()
        md = doc.to_markdown()
        assert "[J]" in md

    def test_apa7_mode_single_language_abstract(self):
        doc = self._make_doc(journal="apa7")
        md = doc.to_markdown()
        assert "Abstract" in md
        assert "摘" not in md.split("---")[-1].split("Abstract")[0]

# cn_norms.json 数据完整性测试已随内置量表库一并移除(feat-186):
# 常模数据已不是发行产物(移到 tests/fixtures/ 仅供机器测试当夹具),
# 再校验一份测试夹具的数据质量没有意义。get_cn_norms 等**机器**的测试仍在下方。


# ---------------------------------------------------------------------------
# get_cn_norms / format_cn_norms_text (scales.py)
# ---------------------------------------------------------------------------

class TestGetCnNorms:
    def test_dass21_has_norms(self):
        n = get_cn_norms("dass-21")
        assert n is not None

    def test_phq9_has_norms(self):
        assert get_cn_norms("phq-9") is not None

    def test_unknown_returns_none(self):
        assert get_cn_norms("nonexistent_scale_xyz") is None

    def test_case_insensitive(self):
        assert get_cn_norms("DASS-21") is not None

    def test_dass21_subscales(self):
        n = get_cn_norms("dass-21")
        assert "Depression" in n["subscales"]
        assert "Anxiety" in n["subscales"]
        assert "Stress" in n["subscales"]

    def test_dass21_mean_values(self):
        n = get_cn_norms("dass-21")
        dep = n["subscales"]["Depression"]
        assert dep["M"] == _approx(6.88)
        assert dep["SD"] == _approx(7.43)

    def test_pss10_has_mean(self):
        n = get_cn_norms("pss-10")
        assert n["subscales"]["Total"]["M"] is not None


class TestFormatCnNormsText:
    def test_returns_string(self):
        out = format_cn_norms_text("dass-21")
        assert isinstance(out, str)

    def test_contains_source(self):
        out = format_cn_norms_text("dass-21")
        assert "Wang" in out or "来源" in out

    def test_contains_subscale_names(self):
        out = format_cn_norms_text("dass-21")
        assert "Depression" in out

    def test_contains_cutoffs(self):
        out = format_cn_norms_text("dass-21")
        assert "轻度" in out or "正常" in out

    def test_warning_included(self):
        out = format_cn_norms_text("phq-9")
        assert "注意" in out or "warning" in out.lower() or "⚠" in out

    def test_unknown_scale_graceful(self):
        out = format_cn_norms_text("no_such_scale")
        assert "暂无" in out or "no_such_scale" in out


# ---------------------------------------------------------------------------
# 自跑块（不依赖 pytest 命令，可用 python tests/test_cn_journal.py 直接验证）
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import traceback

    _SUITES = [
        TestListJournals,
        TestFormatBilingualAbstract,
        TestFormatCnReference,
        TestConvertApaRefToCn,
        TestFormatCnStatMd,
        TestConvertToCnFormat,
        TestCnJournalDocument,
        TestCnNormsData,
        TestGetCnNorms,
        TestFormatCnNormsText,
    ]

    passed = failed = 0
    for suite_cls in _SUITES:
        suite = suite_cls()
        for name in [m for m in dir(suite_cls) if m.startswith("test_")]:
            try:
                getattr(suite, name)()
                passed += 1
                print(f"  PASS  {suite_cls.__name__}.{name}")
            except Exception as exc:
                failed += 1
                print(f"  FAIL  {suite_cls.__name__}.{name}")
                traceback.print_exc()

    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
