"""引用存在性查证:拿条目去真实索引证明其存在(离线测试,getter 全注入)。

守住的核心区分:「查了没有」(not_found,疑似杜撰,硬判据)
            vs「没法查」(unresolvable,网络/收录问题,只提示不拦截)。
两者混同会让整套核查失去公信力——要么放过杜撰,要么把没被索引收录的
中文专著误判成编造。
"""
from __future__ import annotations

import pytest

from psyclaw.psych.cite_verify import (extract_title, verify_entry,
                                       verify_references)

REAL = {"raw": "Duan, X., Ni, X., & Shi, L. (2019). The impact of workplace "
                "violence on job satisfaction. Health Qual Life Outcomes.",
        "surname": "Duan", "year": "2019"}


def _hit(title="The impact of workplace violence on job satisfaction",
         authors=("Xiaojian Duan", "Xin Ni"), year=2019, doi="10.1186/x"):
    return {"message": {"items": [{
        "title": [title], "DOI": doi,
        "issued": {"date-parts": [[year]]},
        "author": [{"given": a.split()[0], "family": a.split()[-1]} for a in authors],
        "container-title": ["Health Qual Life Outcomes"]}]}}


def test_extract_title_from_apa_entry():
    assert extract_title(REAL["raw"]).startswith("The impact of workplace violence")


def test_extract_title_not_cut_by_abbreviation():
    """标题里的 'et al.' / 'U.S.' 等缩写点不该把标题截断。"""
    raw = "Smith, J. (2020). Trust in U.S. institutions after crisis. Journal of X."
    assert "institutions" in extract_title(raw)


def test_verified_when_index_matches_author_and_year():
    r = verify_entry(REAL, getter=lambda url: _hit())
    assert r["status"] == "verified"
    assert "10.1186" in r["note"]


def test_not_found_when_index_returns_nothing():
    r = verify_entry(REAL, getter=lambda url: {"message": {"items": []}})
    assert r["status"] == "not_found"


def test_not_found_when_author_mismatches():
    """近似标题但作者对不上 → 仍算查无此文(防「同题不同文」蒙混）。"""
    r = verify_entry(REAL, getter=lambda url: _hit(authors=("Alice Zhang",)))
    assert r["status"] == "not_found"


def test_not_found_when_year_far_off():
    r = verify_entry(REAL, getter=lambda url: _hit(year=2005))
    assert r["status"] == "not_found"


def test_year_tolerance_allows_online_first_offset():
    """在线优先 vs 见刊年常差 1 年,不该误判成杜撰。"""
    r = verify_entry(REAL, getter=lambda url: _hit(year=2018))
    assert r["status"] == "verified"


def test_network_failure_is_unresolvable_not_fabrication():
    """索引不可达 ≠ 文献不存在——最关键的一条,错了就会把真文献判成编造。"""
    def _boom(url):
        raise OSError("network down")
    r = verify_entry(REAL, getter=_boom)
    assert r["status"] == "unresolvable"
    assert "不作为杜撰判据" in r["note"]


def test_summary_ok_only_when_no_suspect():
    entries = [REAL, dict(REAL, raw="Fake, A. (2021). Nonexistent work.",
                          surname="Fake", year="2021")]
    calls = {"n": 0}

    def _getter(url):
        calls["n"] += 1
        return _hit() if calls["n"] == 1 else {"message": {"items": []}}
    v = verify_references(entries, getter=_getter)
    assert v["verified_n"] == 1 and v["suspect_n"] == 1
    assert v["ok"] is False


def test_unresolvable_never_blocks():
    def _boom(url):
        raise OSError("down")
    v = verify_references([REAL], getter=_boom)
    assert v["unresolvable_n"] == 1 and v["suspect_n"] == 0
    assert v["ok"] is True          # 没法查不构成拦截理由


def test_over_limit_entries_reported_as_skipped_not_silently_dropped():
    """超上限的条目必须如实计入 skipped——静默截断会让「全部通过」名不副实。"""
    entries = [dict(REAL) for _ in range(5)]
    v = verify_references(entries, getter=lambda url: _hit(), limit=2)
    assert v["checked_n"] == 2 and v["skipped"] == 3


@pytest.mark.parametrize("status", ["verified", "not_found", "unresolvable"])
def test_all_three_states_reachable(status):
    getters = {
        "verified": lambda url: _hit(),
        "not_found": lambda url: {"message": {"items": []}},
    }
    if status == "unresolvable":
        def g(url):
            raise OSError("x")
    else:
        g = getters[status]
    assert verify_entry(REAL, getter=g)["status"] == status
