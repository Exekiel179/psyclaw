"""tests/test_embed.py — embed.py 纯函数单元测试 (P5-E3)。

被测：cosine / HashEmbedder._features / HashEmbedder.encode /
      _sha256 / local_model_dir / get_embedder(prefer='hash')

不测 Model2VecEmbedder（依赖 model2vec 包 + 模型权重）。
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from psyclaw.embed import (
    HashEmbedder,
    _sha256,
    cosine,
    get_embedder,
    local_model_dir,
    DEFAULT_MODEL,
)


# ---------------------------------------------------------------------------
# cosine
# ---------------------------------------------------------------------------

class TestCosine:
    def test_identical_vectors_return_1(self):
        v = [1.0, 0.0, 0.0]
        assert abs(cosine(v, v) - 1.0) < 1e-9

    def test_orthogonal_vectors_return_0(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert abs(cosine(a, b)) < 1e-9

    def test_anti_parallel_return_minus_1(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert abs(cosine(a, b) - (-1.0)) < 1e-9

    def test_symmetric(self):
        a = [1.0, 2.0, 3.0]
        b = [4.0, 5.0, 6.0]
        assert abs(cosine(a, b) - cosine(b, a)) < 1e-9

    def test_different_lengths_return_0(self):
        assert cosine([1.0], [1.0, 2.0]) == 0.0

    def test_zero_vector_returns_0(self):
        assert cosine([0.0, 0.0], [1.0, 2.0]) == 0.0

    def test_both_zero_return_0(self):
        assert cosine([0.0], [0.0]) == 0.0

    def test_range_valid(self):
        import random
        rng = random.Random(42)
        a = [rng.gauss(0, 1) for _ in range(64)]
        b = [rng.gauss(0, 1) for _ in range(64)]
        c = cosine(a, b)
        assert -1.0 <= c <= 1.0


# ---------------------------------------------------------------------------
# HashEmbedder._features
# ---------------------------------------------------------------------------

class TestHashEmbedderFeatures:
    def test_english_tokens_extracted(self):
        feats = HashEmbedder._features("the quick brown fox")
        assert "quick" in feats
        assert "brown" in feats

    def test_short_english_words_excluded(self):
        # 少于 3 字符的英文 token 不纳入（模式 [a-z][a-z0-9_-]{2,}）
        feats = HashEmbedder._features("a or is")
        assert all(len(f) >= 3 for f in feats)

    def test_cjk_unigrams(self):
        feats = HashEmbedder._features("心理学研究")
        # 每个汉字应作为 unigram 出现
        assert "心" in feats
        assert "学" in feats

    def test_cjk_bigrams(self):
        feats = HashEmbedder._features("心理学")
        assert "心理" in feats
        assert "理学" in feats

    def test_empty_text(self):
        assert HashEmbedder._features("") == []

    def test_none_text(self):
        assert HashEmbedder._features(None) == []  # type: ignore

    def test_mixed_language(self):
        feats = HashEmbedder._features("分析 regression coefficient")
        assert "分" in feats
        assert "regression" in feats


# ---------------------------------------------------------------------------
# HashEmbedder.encode
# ---------------------------------------------------------------------------

class TestHashEmbedderEncode:
    def setup_method(self):
        self.emb = HashEmbedder()

    def test_dim_is_256(self):
        result = self.emb.encode(["hello"])
        assert len(result[0]) == 256

    def test_single_text_normalized(self):
        vecs = self.emb.encode(["心理学研究方法"])
        v = vecs[0]
        norm = math.sqrt(sum(x * x for x in v))
        assert abs(norm - 1.0) < 1e-6

    def test_multiple_texts(self):
        texts = ["anova", "regression", "mediation"]
        vecs = self.emb.encode(texts)
        assert len(vecs) == 3
        for v in vecs:
            assert len(v) == 256

    def test_deterministic(self):
        text = "PsyClaw statistical analysis"
        v1 = self.emb.encode([text])[0]
        v2 = self.emb.encode([text])[0]
        assert v1 == v2

    def test_different_texts_different_vectors(self):
        v1 = self.emb.encode(["anova"])[0]
        v2 = self.emb.encode(["regression"])[0]
        assert v1 != v2

    def test_similar_texts_higher_cosine(self):
        vecs = self.emb.encode(["ANOVA 方差分析", "方差分析 ANOVA", "linear regression"])
        s_similar = cosine(vecs[0], vecs[1])
        s_different = cosine(vecs[0], vecs[2])
        assert s_similar > s_different

    def test_empty_text_no_crash(self):
        vecs = self.emb.encode([""])
        assert len(vecs) == 1
        v = vecs[0]
        assert len(v) == 256
        # 零向量时 norm=0 → vec 未归一，所有元素为0
        assert all(x == 0.0 for x in v) or all(math.isfinite(x) for x in v)

    def test_empty_list(self):
        assert self.emb.encode([]) == []


# ---------------------------------------------------------------------------
# HashEmbedder 常量
# ---------------------------------------------------------------------------

class TestHashEmbedderConstants:
    def test_name(self):
        assert HashEmbedder.name == "hash-ngram-256"

    def test_dim(self):
        assert HashEmbedder.dim == 256

    def test_default_threshold(self):
        assert 0.0 < HashEmbedder.default_threshold < 1.0


# ---------------------------------------------------------------------------
# _sha256
# ---------------------------------------------------------------------------

class TestSha256:
    def test_known_hash(self, tmp_path):
        p = tmp_path / "test.txt"
        p.write_bytes(b"hello")
        # sha256("hello") = 2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824
        h = _sha256(p)
        assert h == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.bin"
        p.write_bytes(b"")
        h = _sha256(p)
        # sha256("") = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
        assert h == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def test_different_content_different_hash(self, tmp_path):
        p1 = tmp_path / "a.bin"
        p2 = tmp_path / "b.bin"
        p1.write_bytes(b"aaa")
        p2.write_bytes(b"bbb")
        assert _sha256(p1) != _sha256(p2)

    def test_returns_hex_string(self, tmp_path):
        p = tmp_path / "x.bin"
        p.write_bytes(b"x")
        h = _sha256(p)
        assert isinstance(h, str)
        assert all(c in "0123456789abcdef" for c in h)
        assert len(h) == 64


# ---------------------------------------------------------------------------
# local_model_dir
# ---------------------------------------------------------------------------

class TestLocalModelDir:
    def test_contains_model_name_tail(self):
        d = local_model_dir("org/my-model-v2")
        assert d.name == "my-model-v2"

    def test_default_model(self):
        d = local_model_dir(DEFAULT_MODEL)
        assert "potion-multilingual-128M" in str(d)

    def test_is_path(self):
        assert isinstance(local_model_dir(), Path)


# ---------------------------------------------------------------------------
# get_embedder
# ---------------------------------------------------------------------------

class TestGetEmbedder:
    def test_prefer_hash_returns_hash_embedder(self):
        emb = get_embedder(prefer="hash")
        assert isinstance(emb, HashEmbedder)

    def test_env_hash_returns_hash_embedder(self, monkeypatch):
        monkeypatch.setenv("PSYCLAW_EMBED_BACKEND", "hash")
        # 重置缓存以确保每次走新的分支
        import psyclaw.embed as em
        monkeypatch.setattr(em, "_CACHED", None)
        emb = get_embedder()
        assert isinstance(emb, HashEmbedder)

    def test_hash_embedder_encodes_text(self):
        emb = get_embedder(prefer="hash")
        vecs = emb.encode(["test"])
        assert len(vecs) == 1
        assert len(vecs[0]) == emb.dim
