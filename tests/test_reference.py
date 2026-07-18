"""feat(cite/引用文章):把文献元数据格式化成规范参考文献 + 文内引用。

cite = 引用文章(本模块:元数据→APA7 参考文献条目 + 文内引用)+ 引文核查(citations.py)。
纯字符串格式化,无网络、无统计——守铁律。给作者/年/题/刊/卷期页/doi 就产出可直接
粘进参考文献表的条目,并给叙述式与夹注式两种文内引用,免去手排格式的活。
"""
from __future__ import annotations

from psyclaw.psych.reference import (
    format_reference,
    intext_citation,
    parse_author,
)


def test_parse_author_comma_form():
    assert parse_author("Hamaker, Ellen L.") == ("Hamaker", "E. L.")


def test_parse_author_natural_form():
    assert parse_author("Ellen L. Hamaker") == ("Hamaker", "E. L.")


def test_format_reference_journal_apa7():
    meta = {
        "authors": ["Ellen L. Hamaker", "Rebecca M. Kuiper"],
        "year": "2015",
        "title": "A critique of the cross-lagged panel model",
        "journal": "Psychological Methods",
        "volume": "20", "issue": "1", "pages": "102-116",
        "doi": "10.1037/a0038889",
    }
    ref = format_reference(meta)
    assert "Hamaker, E. L., & Kuiper, R. M. (2015底".replace("底", "") in ref or "Hamaker, E. L., & Kuiper, R. M. (2015)" in ref
    assert "A critique of the cross-lagged panel model." in ref
    assert "Psychological Methods, 20(1), 102–116" in ref     # 期刊斜体名+卷(期), en dash 页码
    assert "https://doi.org/10.1037/a0038889" in ref


def test_intext_two_authors_parenthetical_vs_narrative():
    meta = {"authors": ["Ellen L. Hamaker", "Rebecca M. Kuiper"], "year": "2015"}
    assert intext_citation(meta, paren=True) == "(Hamaker & Kuiper, 2015)"
    assert intext_citation(meta, paren=False) == "Hamaker and Kuiper (2015)"


def test_intext_three_plus_uses_etal():
    meta = {"authors": ["A B Smith", "C D Jones", "E F Lee"], "year": "2020"}
    assert intext_citation(meta, paren=True) == "(Smith et al., 2020)"
    assert intext_citation(meta, paren=False) == "Smith et al. (2020)"


def test_intext_single_author():
    meta = {"authors": ["Jane Q. Public"], "year": "2019"}
    assert intext_citation(meta, paren=True) == "(Public, 2019)"


def test_reference_seven_plus_authors_etal_rule():
    # APA7:>20 作者才 et al.;7 作者应全列
    authors = [f"F{i} L{i}" for i in range(7)]
    meta = {"authors": authors, "year": "2021", "title": "T", "journal": "J",
            "volume": "1", "pages": "1-2"}
    ref = format_reference(meta)
    assert "L6, F." in ref            # 第7位作者仍在
    assert "et al." not in ref


def test_reference_over_20_authors_etal():
    authors = [f"F{i} L{i}" for i in range(25)]
    meta = {"authors": authors, "year": "2021", "title": "T", "journal": "J"}
    ref = format_reference(meta)
    assert "..." in ref               # 省略号
    assert "L24" in ref               # 最后一位仍列出


def test_reference_missing_optional_fields_graceful():
    meta = {"authors": ["Jane Public"], "year": "2019",
            "title": "A minimal record", "journal": "Some Journal"}
    ref = format_reference(meta)
    assert "Public, J. (2019). A minimal record. Some Journal" in ref
    assert ref.endswith(".") or ref.endswith("Journal.")   # 无卷期页也收尾干净


def test_no_stats_import_in_module():
    import inspect
    import psyclaw.psych.reference as M
    src = inspect.getsource(M)
    for banned in ("import scipy", "import numpy", "import statsmodels", "import pingouin"):
        assert banned not in src


def test_empty_authors_graceful():
    ref = format_reference({"authors": [], "year": "2020", "title": "T", "journal": "J"})
    assert "(2020)" in ref and "T." in ref


# ---- cite --make CLI 路由 -----------------------------------------------------

def test_cmd_cite_make_generates(tmp_path, capsys):
    import argparse
    import json
    from psyclaw.cli import cmd_cite
    p = tmp_path / "refs.json"
    p.write_text(json.dumps({
        "authors": ["Ellen L. Hamaker", "Rebecca M. Kuiper"], "year": "2015",
        "title": "A critique of the cross-lagged panel model",
        "journal": "Psychological Methods", "volume": "20", "issue": "1",
        "pages": "102-116", "doi": "10.1037/a0038889",
    }), encoding="utf-8")
    rc = cmd_cite(argparse.Namespace(make=str(p), manuscript=None,
                                     project=".", journal=None))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Hamaker, E. L., & Kuiper, R. M. (2015)" in out
    assert "(Hamaker & Kuiper, 2015)" in out       # 文内引用也给


def test_cmd_cite_needs_arg(capsys):
    import argparse
    from psyclaw.cli import cmd_cite
    rc = cmd_cite(argparse.Namespace(make=None, manuscript=None,
                                     project=".", journal=None))
    assert rc == 2                                   # 既无稿件也无 --make


def test_cmd_cite_make_bad_json(tmp_path, capsys):
    import argparse
    from psyclaw.cli import cmd_cite
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    rc = cmd_cite(argparse.Namespace(make=str(p), manuscript=None,
                                     project=".", journal=None))
    assert rc == 2                                   # 坏 JSON 不抛,rc=2
