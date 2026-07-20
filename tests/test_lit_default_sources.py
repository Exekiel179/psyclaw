"""默认检索源只能有一份真源——CLI 不得另抄一份(必然漂移)。

历史事故:feat-177 给 litsearch.search() 的默认源加了 Crossref(中文核心期刊 DOI
覆盖最好的源,正是为它才加的),但 lit_cli 自留了一份硬编码 "openalex,europepmc"
没同步 → 走 lit_search 工具有 Crossref、走 `psyclaw lit` 命令没有,同一次检索
两条路径结果不同,且无人察觉。
"""
from __future__ import annotations

import inspect

from psyclaw.psych import lit_cli as lc
from psyclaw.psych import litsearch


def test_search_default_sources_include_crossref():
    src = inspect.getsource(litsearch.search)
    assert "crossref" in src, "Crossref 是中文核心期刊 DOI 覆盖的关键源"


def test_lit_cli_does_not_hardcode_its_own_source_list():
    """CLI 代码里不得出现自己的默认源列表——有就是又抄了一份。

    只看代码,剥掉注释:注释里为记录这段历史必然要引用那个字符串。
    """
    code = "\n".join(ln.split("#")[0] for ln in
                     inspect.getsource(lc).splitlines())
    assert "openalex,europepmc" not in code, (
        "lit_cli 又硬编码了一份默认源;默认应交给 litsearch.search 决定")


def test_lit_cli_passes_none_so_search_owns_default(monkeypatch):
    """空 sources 必须传 None(而非空列表)——空列表会被当成「一个源都不要」。"""
    seen = {}

    def _fake_search(query, sources=None, limit=10, year_from=None):
        seen["sources"] = sources
        return {"results": [], "per_source": {}, "n_raw": 0,
                "n_deduped": 0, "n_duplicates": 0}
    monkeypatch.setattr(litsearch, "search", _fake_search)
    lc.lit_cli("burnout", project_dir=".")
    assert seen["sources"] is None


def test_explicit_sources_still_respected(monkeypatch):
    seen = {}

    def _fake_search(query, sources=None, limit=10, year_from=None):
        seen["sources"] = sources
        return {"results": [], "per_source": {}, "n_raw": 0,
                "n_deduped": 0, "n_duplicates": 0}
    monkeypatch.setattr(litsearch, "search", _fake_search)
    lc.lit_cli("burnout", sources="arxiv", project_dir=".")
    assert seen["sources"] == ["arxiv"]
