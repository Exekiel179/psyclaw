"""feat-104:文献矩阵 + 桥接结果导入(路线 B 回灌闭环)。"""

from __future__ import annotations

import json

from psyclaw.psych.litmatrix import (
    build_matrix_md,
    import_results,
    parse_bridge_results,
    write_matrix,
)

_BRIDGE_MD = """# 桥接检索结果

| 标题 | 作者 | 年份 | 来源 | 关键词 | 摘要 | 链接 |
|------|------|------|------|--------|------|------|
| 心理电子沙盘系统设计 | 王明; 李红 | 2021 | 心理科学 | 沙盘;数字化 | 设计了一套系统 | http://x |
| Digital sandplay therapy | Smith, J. & Lee, K. | 2023 | Front Psychol | sandplay | 未显示 | 未显示 |
| | 无标题作者 | 2020 | 某刊 | | | |
"""


def test_parse_markdown_table():
    r = parse_bridge_results(_BRIDGE_MD)
    assert len(r["papers"]) == 2 and r["skipped"] == 1     # 缺标题剔除并计数
    p1 = r["papers"][0]
    assert p1["title"] == "心理电子沙盘系统设计"
    assert p1["authors"] == ["王明", "李红"] and p1["year"] == 2021
    assert p1["source"].startswith("bridge:")
    p2 = r["papers"][1]
    assert p2["abstract"] == ""            # 「未显示」如实置空,不编造


def test_parse_csv_fallback():
    csv_text = "title,authors,year,source\nA study,Zhang,2019,J Test\n"
    r = parse_bridge_results(csv_text)
    assert len(r["papers"]) == 1 and r["papers"][0]["year"] == 2019


def test_import_merges_and_dedups(tmp_path):
    f = tmp_path / "bridge_results.md"
    f.write_text(_BRIDGE_MD, encoding="utf-8")
    r1 = import_results(str(f), project_dir=str(tmp_path))
    assert r1["added"] == 2 and r1["total"] == 2
    r2 = import_results(str(f), project_dir=str(tmp_path))   # 重复导入全去重
    assert r2["added"] == 0 and r2["duplicates"] == 2 and r2["total"] == 2
    corpus = json.loads((tmp_path / "notes" / "lit_search.json")
                        .read_text(encoding="utf-8"))
    assert corpus["n_deduped"] == 2 and corpus["per_source"]["bridge"] == 2
    prisma = (tmp_path / "notes" / "prisma_search.md").read_text(encoding="utf-8")
    assert "机构库导入" in prisma and "缺标题剔除 1" in prisma


def test_matrix_md_fields_and_honesty():
    papers = parse_bridge_results(_BRIDGE_MD)["papers"]
    md, emap = build_matrix_md(papers, topic="心理电子沙盘")
    assert "文献矩阵 — 心理电子沙盘" in md
    for field in ("研究对象", "研究方法", "主要发现", "局限", "纳入?"):
        assert field in md
    assert "待核查" in md and "全文未获取" in md      # 诚实约定内嵌
    assert "screening_criteria.json" in md            # 引用预先声明的标准
    assert len(emap.get("references", [])) == 2      # 键语料同步产出


def test_write_matrix_creates_files_and_citecheck_corpus(tmp_path):
    f = tmp_path / "bridge_results.md"
    f.write_text(_BRIDGE_MD, encoding="utf-8")
    import_results(str(f), project_dir=str(tmp_path))
    r = write_matrix(project_dir=str(tmp_path), topic="电子沙盘")
    assert r["n"] == 2
    assert (tmp_path / "notes" / "lit_matrix.md").exists()
    # cite-check 语料打通:load_allowed 直接读到导入条目的键
    from psyclaw.psych.citations import load_allowed
    keys, source = load_allowed(str(tmp_path))
    assert source == "notes/evidence_map.json" and len(keys) == 2


def test_write_matrix_fail_closed_without_corpus(tmp_path):
    import pytest
    with pytest.raises(ValueError, match="无检索语料"):
        write_matrix(project_dir=str(tmp_path))
