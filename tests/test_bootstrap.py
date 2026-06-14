"""tests/test_bootstrap.py — bootstrap.py 能力检测单元测试 (P5-E5)。

被测：_has_module / detect / DEP_GROUPS / EXTERNAL_BINS
"""
from __future__ import annotations

import pytest

from psyclaw.bootstrap import (
    DEP_GROUPS,
    EXTERNAL_BINS,
    _has_module,
    detect,
)


# ---------------------------------------------------------------------------
# _has_module
# ---------------------------------------------------------------------------

class TestHasModule:
    def test_stdlib_module_found(self):
        # json 始终存在
        assert _has_module("json") is True

    def test_stdlib_math_found(self):
        assert _has_module("math") is True

    def test_nonexistent_returns_false(self):
        assert _has_module("no_such_module_xyz_12345") is False

    def test_empty_string_returns_false(self):
        assert _has_module("") is False

    def test_psyclaw_itself_found(self):
        assert _has_module("psyclaw") is True


# ---------------------------------------------------------------------------
# DEP_GROUPS / EXTERNAL_BINS 常量结构
# ---------------------------------------------------------------------------

class TestConstants:
    def test_dep_groups_has_required_keys(self):
        for key in ("stats", "viz", "eeg", "full", "embed"):
            assert key in DEP_GROUPS

    def test_dep_groups_value_structure(self):
        for key, (desc, pkgs) in DEP_GROUPS.items():
            assert isinstance(desc, str) and desc
            assert isinstance(pkgs, list)
            for pip_name, import_name in pkgs:
                assert isinstance(pip_name, str)
                assert isinstance(import_name, str)

    def test_external_bins_has_keys(self):
        for key in ("R", "SPSS", "Mplus", "Stata"):
            assert key in EXTERNAL_BINS

    def test_external_bins_value_structure(self):
        for name, (cands, desc) in EXTERNAL_BINS.items():
            assert isinstance(cands, list) and cands
            assert isinstance(desc, str)


# ---------------------------------------------------------------------------
# detect
# ---------------------------------------------------------------------------

class TestDetect:
    def test_returns_dict_with_groups_and_bins(self):
        result = detect()
        assert "groups" in result
        assert "bins" in result

    def test_groups_has_all_keys(self):
        result = detect()
        for key in DEP_GROUPS:
            assert key in result["groups"]

    def test_bins_has_all_keys(self):
        result = detect()
        for name in EXTERNAL_BINS:
            assert name in result["bins"]

    def test_group_entry_structure(self):
        result = detect()
        for key, info in result["groups"].items():
            assert "desc" in info
            assert "have" in info
            assert "missing" in info
            assert "ready" in info
            assert isinstance(info["ready"], bool)
            assert isinstance(info["have"], list)
            assert isinstance(info["missing"], list)

    def test_bin_entry_structure(self):
        result = detect()
        for name, info in result["bins"].items():
            assert "desc" in info
            assert "path" in info
            assert "ready" in info
            assert isinstance(info["ready"], bool)

    def test_stdlib_not_in_missing(self):
        """stdlib 模块不在 DEP_GROUPS 里，不会误报为缺失。"""
        result = detect()
        for key, info in result["groups"].items():
            # missing 中的 import_name 应该是已知的第三方库
            for _, imp in info["missing"]:
                assert not _has_module(imp)  # 缺失的确实不能 import

    def test_ready_consistency(self):
        """ready = (have 长度 == pkgs 总数)。"""
        result = detect()
        for key, info in result["groups"].items():
            expected_total = len(DEP_GROUPS[key][1])
            n_have = len(info["have"])
            n_missing = len(info["missing"])
            assert n_have + n_missing == expected_total
            assert info["ready"] == (n_missing == 0)

    def test_reproducible(self):
        """两次调用结果一致（纯函数，不依赖全局状态）。"""
        r1 = detect()
        r2 = detect()
        for key in r1["groups"]:
            assert r1["groups"][key]["ready"] == r2["groups"][key]["ready"]
