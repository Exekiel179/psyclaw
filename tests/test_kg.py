"""带引用轻量 KG 测试 —— 节点去重 / 边必带来源 / 邻居·子图 / 种图 / 溯源核验。"""

from __future__ import annotations

import json

from psyclaw.kg import KnowledgeGraph, render_mermaid


def _kg(tmp_path):
    return KnowledgeGraph(str(tmp_path))


def test_add_node_dedup(tmp_path):
    kg = _kg(tmp_path)
    a = kg.add_node("Working Memory", "construct")
    b = kg.add_node("working memory", "construct")   # 归一后同名 → 同 id
    assert a == b
    c = kg.add_node("Working Memory", "paper")        # 类型不同 → 不同 id
    assert c != a


def test_add_edge_requires_source(tmp_path):
    kg = _kg(tmp_path)
    assert kg.add_edge("A", "construct", "rel", "B", "paper", source_ref="") is None
    assert kg.add_edge("A", "construct", "rel", "B", "paper", source_ref=None) is None
    eid = kg.add_edge("A", "construct", "rel", "B", "paper", source_ref="Smith (2020)")
    assert eid is not None


def test_add_edge_creates_nodes_and_stats(tmp_path):
    kg = _kg(tmp_path)
    kg.add_edge("焦虑", "construct", "研究见于", "Smith (2020)", "paper",
                source_ref="Smith (2020)")
    s = kg.stats()
    assert s["nodes"] == 2 and s["edges"] == 1
    assert s["uncited"] == 0          # 由构造:无来源边恒为 0


def test_neighbors_out_and_in(tmp_path):
    kg = _kg(tmp_path)
    kg.add_edge("焦虑", "construct", "研究见于", "Smith (2020)", "paper",
                source_ref="Smith (2020)")
    out = kg.neighbors("焦虑")
    assert out and out[0]["dir"] == "→" and out[0]["other"] == "Smith (2020)"
    inn = kg.neighbors("Smith (2020)")
    assert inn and inn[0]["dir"] == "←" and inn[0]["other"] == "焦虑"


def test_subgraph_depth(tmp_path):
    kg = _kg(tmp_path)
    kg.add_edge("焦虑", "construct", "研究见于", "P1", "paper", source_ref="P1")
    kg.add_edge("P1", "paper", "作者", "Smith", "person", source_ref="P1")
    sub = kg.subgraph("焦虑", depth=2)
    names = {n["name"] for n in sub["nodes"]}
    assert {"焦虑", "P1", "Smith"} <= names
    assert len(sub["edges"]) == 2


def _write_emap(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir(exist_ok=True)
    (notes / "evidence_map.json").write_text(json.dumps({
        "references": [{"key": "Smith et al. (2020)"}, {"key": "Doe (2019)"}],
        "themes": [{"term": "焦虑", "cites": ["Smith et al. (2020)", "Doe (2019)"]}],
    }), encoding="utf-8")


def test_seed_from_evidence_map(tmp_path):
    _write_emap(tmp_path)
    kg = _kg(tmp_path)
    r = kg.seed_from_evidence_map(str(tmp_path))
    assert r["added"] == 2
    # 构念 + 2 篇论文 = 3 节点
    assert kg.stats()["nodes"] == 3
    assert {n["other"] for n in kg.neighbors("焦虑")} == {"Smith et al. (2020)", "Doe (2019)"}


def test_seed_missing_evidence_map(tmp_path):
    r = _kg(tmp_path).seed_from_evidence_map(str(tmp_path))
    assert r["added"] == 0 and "evidence_map" in r["error"]


def test_verify_grounded_and_orphan(tmp_path):
    _write_emap(tmp_path)
    kg = _kg(tmp_path)
    kg.seed_from_evidence_map(str(tmp_path))          # 全部来源在语料
    v0 = kg.verify(str(tmp_path))
    assert v0["no_orphan_relations"] is True
    assert v0["grounded"] == v0["citation_edges"] == 2
    # 加一条来源杜撰的关系边 → 应被 verify 抓成孤儿
    kg.add_edge("焦虑", "construct", "研究见于", "Ghost et al. (2099)", "paper",
                source_ref="Ghost et al. (2099)")
    v1 = kg.verify(str(tmp_path))
    assert v1["no_orphan_relations"] is False
    assert any("Ghost" in o["source_ref"] for o in v1["orphans"])


def test_non_citation_edges_skipped_by_verify(tmp_path):
    _write_emap(tmp_path)
    kg = _kg(tmp_path)
    # 来源类型非 citation(如会话) → 不参与 citation 溯源核验
    kg.add_edge("焦虑", "construct", "提及于", "s1", "session",
                source_ref="session:abc", source_kind="session")
    v = kg.verify(str(tmp_path))
    assert v["citation_edges"] == 0 and v["no_orphan_relations"] is True


def test_render_mermaid(tmp_path):
    kg = _kg(tmp_path)
    kg.add_edge("焦虑", "construct", "研究见于", "Smith (2020)", "paper",
                source_ref="Smith (2020)")
    out = render_mermaid(kg.subgraph("焦虑"))
    assert "mermaid" in out and "焦虑" in out and "研究见于" in out
