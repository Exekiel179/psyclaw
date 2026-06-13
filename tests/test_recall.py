"""上下文召回 + 审计解析测试。

原则:相关度不达标不注入(fail-closed);
审计 SCORE/VERDICT 解析不到按 IMPROVE。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ["PSYCLAW_EMBED_BACKEND"] = "hash"   # 测试确定性:不加载真模型

from psyclaw.audit import parse_audit  # noqa: E402
from psyclaw.embed import HashEmbedder, cosine, get_embedder  # noqa: E402
from psyclaw.recall import (ContextArchive, extract_keywords,  # noqa: E402
                            render_recall)


# ---------------------------------------------------------------------------
# 关键词抽取
# ---------------------------------------------------------------------------

def test_extract_fixed_and_english():
    kws = extract_keywords("用 t检验 比较两组焦虑得分,数据在 anxiety.csv,效应量要报")
    assert "t检验" in kws and "焦虑" in kws and "效应量" in kws
    assert "anxiety" in kws
    assert "csv" not in kws  # 停用词


def test_extract_nothing_is_empty():
    assert extract_keywords("今天天气如何") == set()


# ---------------------------------------------------------------------------
# 存储 + 召回门控
# ---------------------------------------------------------------------------

def _seed(tmp_path) -> ContextArchive:
    arc = ContextArchive(tmp_path)
    arc.record("s1", "两组焦虑得分用什么检验?",
               "建议独立样本 t检验,先查正态与方差齐性,报效应量 Cohen's d。")
    arc.record("s1", "中介效应怎么做?",
               "用 bootstrap 中介分析,报间接效应及其置信区间。")
    return arc


def test_recall_hits_above_threshold(tmp_path):
    arc = _seed(tmp_path)
    hits = arc.recall("焦虑数据 t检验 的效应量怎么报", threshold=0.8)
    assert len(hits) == 1
    assert hits[0]["score"] >= 0.8
    assert "t检验" in hits[0]["user_text"] + hits[0]["reply_text"]
    block = render_recall(hits)
    assert "相关度" in block and "历史上下文召回" in block


def test_recall_below_threshold_returns_nothing(tmp_path):
    arc = _seed(tmp_path)
    # 查询关键词大多不在库里 → 覆盖率低于门槛,不注入
    assert arc.recall("eeg 脑电 erp 成分 P300 振幅 焦虑", threshold=0.8) == []
    # 无关键词的查询直接空
    assert arc.recall("你好呀") == []


def test_recall_excludes_session(tmp_path):
    arc = _seed(tmp_path)
    assert arc.recall("焦虑 t检验 效应量", exclude_session="s1") == []


def test_archive_stats(tmp_path):
    arc = _seed(tmp_path)
    n_turns, n_kws = arc.stats()
    assert n_turns == 2 and n_kws > 0
    # 全新目录:不建库,0/0
    assert ContextArchive(tmp_path / "empty").stats() == (0, 0)


# ---------------------------------------------------------------------------
# 本地 embedding(哈希兜底确定性 + 语义通道召回)
# ---------------------------------------------------------------------------

def test_hash_embedder_deterministic_and_normalized():
    emb = HashEmbedder()
    v1, v2 = emb.encode(["量表信度怎么算"] * 2)
    assert v1 == v2 and len(v1) == emb.dim
    assert abs(sum(x * x for x in v1) - 1.0) < 1e-9   # L2 归一
    assert cosine(v1, v2) > 0.999


def test_hash_cosine_related_vs_unrelated():
    emb = HashEmbedder()
    a, b, c = emb.encode(["伦理审查申请表的提交流程",
                          "提交伦理审查申请表需要什么流程",
                          "方差分析的事后比较怎么做"])
    assert cosine(a, b) > cosine(a, c)
    assert cosine(a, b) >= emb.default_threshold


def test_semantic_recall_without_fixed_keywords(tmp_path):
    """固定词表完全不命中时,语义通道仍能召回(真·embedding 路径)。"""
    arc = ContextArchive(tmp_path, embedder=HashEmbedder())
    arc.record("s1", "被试招募的伦理审查流程?",
               "先提交伦理审查申请表,获批后再发放知情同意书。")
    hits = arc.recall("伦理审查申请表的流程")
    assert len(hits) == 1 and hits[0]["channel"] == "语义"
    assert hits[0]["score"] >= HashEmbedder.default_threshold
    # 无关查询:两通道都不达标 → 不注入
    assert arc.recall("方差分析的事后比较怎么做") == []


def test_reindex_backfills_new_model(tmp_path):
    class StubEmbedder:
        name, dim, default_threshold = "stub-4", 4, 0.9

        def encode(self, texts):
            return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

    arc = ContextArchive(tmp_path, embedder=HashEmbedder())
    arc.record("s1", "问A", "答A")
    arc.record("s1", "问B", "答B")
    # 换模型 → 旧向量按模型名分桶,新模型缺 2 条 → 补 2;再跑幂等
    arc2 = ContextArchive(tmp_path, embedder=StubEmbedder())
    assert arc2.reindex() == 2
    assert arc2.reindex() == 0


def test_get_embedder_prefer_hash():
    assert get_embedder(prefer="hash").name == HashEmbedder.name


# ---------------------------------------------------------------------------
# 审计解析(fail-closed)
# ---------------------------------------------------------------------------

def test_parse_audit_pass():
    text = "SCORE: 92\n问题: 无\n改进: 无\nAUDIT_VERDICT: PASS"
    assert parse_audit(text) == (92, "PASS")


def test_parse_audit_improve():
    text = "SCORE: 55\n问题: 没报效应量\n改进: 补 Cohen's d\nAUDIT_VERDICT: IMPROVE"
    assert parse_audit(text) == (55, "IMPROVE")


def test_parse_audit_failclosed():
    # 没有任何标记 → (None, IMPROVE),不猜分数
    assert parse_audit("回答看起来不错。") == (None, "IMPROVE")
    # 正文提到 SCORE 不在行首仍可被行首正则拒绝
    assert parse_audit("  我觉得 SCORE 应该是 90")[1] == "IMPROVE"
    # 分数封顶 100
    assert parse_audit("SCORE: 250\nAUDIT_VERDICT: PASS")[0] == 100
