"""tests/test_path_ingest.py — R-5 本地文件路径检测与路由测试。

验收标准：
- 路径识别（含反斜杠/引号/相对/绝对/~展开）
- CSV 路由到元数据注入而非原始数据
- 文本文件走摘录
- 缺失文件友好报错
- 原始文件未被修改
- 25+ 例
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from psyclaw.path_ingest import (
    DATA_SUFFIXES,
    TEXT_SUFFIXES,
    classify,
    extract_paths,
    process_message,
    _data_metadata,
    _is_num,
)


# ---------------------------------------------------------------------------
# 辅助：创建临时文件
# ---------------------------------------------------------------------------

def _make_csv(tmp: Path, name: str = "data.csv", *, rows: int = 20) -> Path:
    p = tmp / name
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "score", "group"])
        for i in range(rows):
            w.writerow([i + 1, 50 + i * 0.5, "A" if i % 2 == 0 else "B"])
    return p


def _make_text(tmp: Path, name: str = "notes.md", content: str = "Hello\nWorld") -> Path:
    p = tmp / name
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# extract_paths
# ---------------------------------------------------------------------------

class TestExtractPaths:
    def test_unix_absolute_existing(self, tmp_path):
        csv_p = _make_csv(tmp_path)
        paths = extract_paths(f"请分析 {csv_p} 的数据", cwd=tmp_path)
        assert csv_p in paths

    def test_relative_path(self, tmp_path):
        csv_p = _make_csv(tmp_path)
        rel = "./data.csv"
        paths = extract_paths(f"看看 {rel}", cwd=tmp_path)
        assert csv_p in paths

    def test_dotdot_relative(self, tmp_path):
        csv_p = _make_csv(tmp_path)
        sub = tmp_path / "subdir"
        sub.mkdir()
        paths = extract_paths("../data.csv", cwd=sub)
        assert csv_p in paths

    def test_double_quoted_path(self, tmp_path):
        csv_p = _make_csv(tmp_path, "my data.csv")
        paths = extract_paths(f'分析 "{csv_p}"', cwd=tmp_path)
        assert csv_p in paths

    def test_single_quoted_path(self, tmp_path):
        txt_p = _make_text(tmp_path)
        paths = extract_paths(f"读取 '{txt_p}'", cwd=tmp_path)
        assert txt_p in paths

    def test_tilde_expansion(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        csv_p = home / "data.csv"
        _make_csv(home, "data.csv")
        paths = extract_paths("分析 ~/data.csv", cwd=tmp_path)
        assert csv_p in paths

    def test_trailing_punctuation_stripped(self, tmp_path):
        csv_p = _make_csv(tmp_path)
        # 句号紧跟路径
        paths = extract_paths(f"请看 {csv_p}。", cwd=tmp_path)
        assert csv_p in paths

    def test_non_existing_path_not_returned(self, tmp_path):
        paths = extract_paths("/nonexistent/file.csv", cwd=tmp_path)
        assert not any(p.name == "file.csv" for p in paths)

    def test_deduplication(self, tmp_path):
        csv_p = _make_csv(tmp_path)
        text = f"分析 {csv_p} 再看 {csv_p}"
        paths = extract_paths(text, cwd=tmp_path)
        assert paths.count(csv_p) == 1

    def test_multiple_different_paths(self, tmp_path):
        p1 = _make_csv(tmp_path, "a.csv")
        p2 = _make_text(tmp_path, "b.md")
        paths = extract_paths(f"看 {p1} 和 {p2}", cwd=tmp_path)
        assert p1 in paths
        assert p2 in paths

    def test_slash_command_not_matched(self, tmp_path):
        # REPL slash 命令不是文件路径，即使语法上像 /method
        paths = extract_paths("/help /model /stat", cwd=tmp_path)
        # 这些 slash 命令不应作为文件路径被找到（不存在）
        assert len(paths) == 0

    def test_windows_path_pattern(self, tmp_path):
        # 模拟 Windows 路径识别（不检查文件存在，只验证正则）
        from psyclaw.path_ingest import _PATH_RE
        text = r'分析 C:\Users\data.csv'
        matches = [next(g for g in m.groups() if g is not None)
                   for m in _PATH_RE.finditer(text)]
        assert any("data.csv" in m for m in matches)


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------

class TestClassify:
    @pytest.mark.parametrize("suffix", [".csv", ".tsv", ".sav", ".xlsx", ".xls"])
    def test_data_suffixes(self, tmp_path, suffix):
        p = tmp_path / f"file{suffix}"
        p.touch()
        assert classify(p) == "data"

    @pytest.mark.parametrize("suffix", [".md", ".txt", ".py", ".json", ".yaml",
                                          ".yml", ".r", ".tex", ".rst"])
    def test_text_suffixes(self, tmp_path, suffix):
        p = tmp_path / f"file{suffix}"
        p.touch()
        assert classify(p) == "text"

    def test_unknown_suffix(self, tmp_path):
        p = tmp_path / "file.xyz"
        p.touch()
        assert classify(p) == "unknown"

    def test_case_insensitive(self, tmp_path):
        p = tmp_path / "DATA.CSV"
        p.touch()
        assert classify(p) == "data"


# ---------------------------------------------------------------------------
# _data_metadata
# ---------------------------------------------------------------------------

class TestDataMetadata:
    def test_contains_column_names(self, tmp_path):
        p = _make_csv(tmp_path)
        meta = _data_metadata(p)
        assert "id" in meta
        assert "score" in meta
        assert "group" in meta

    def test_contains_path(self, tmp_path):
        p = _make_csv(tmp_path)
        meta = _data_metadata(p)
        assert str(p) in meta

    def test_no_raw_data_rows(self, tmp_path):
        p = _make_csv(tmp_path, rows=10)
        meta = _data_metadata(p)
        # 原始数值不应大量出现（前3行样本用于类型推断，但元数据不保留原始行）
        assert "<data_file" in meta
        assert "原始数据行未进入对话" in meta

    def test_analysis_hint_present(self, tmp_path):
        p = _make_csv(tmp_path)
        meta = _data_metadata(p)
        assert "psyclaw" in meta.lower() or "describe" in meta

    def test_col_types_detected(self, tmp_path):
        p = _make_csv(tmp_path)
        meta = _data_metadata(p)
        assert "数值" in meta or "文本" in meta

    def test_row_count_present(self, tmp_path):
        p = _make_csv(tmp_path, rows=15)
        meta = _data_metadata(p)
        assert "rows" in meta


# ---------------------------------------------------------------------------
# process_message — 核心路由逻辑
# ---------------------------------------------------------------------------

class TestProcessMessage:
    def test_csv_context_contains_metadata_not_raw(self, tmp_path):
        p = _make_csv(tmp_path, rows=5)
        ctx, errors = process_message(f"分析 {p}", cwd=tmp_path)
        assert ctx  # 有注入内容
        assert "<data_file" in ctx
        assert "原始数据行未进入对话" in ctx
        assert errors == []

    def test_csv_raw_data_not_in_context(self, tmp_path):
        p = _make_csv(tmp_path, rows=5)
        ctx, _ = process_message(f"请看 {p}", cwd=tmp_path)
        # 原始数据行（如 "1,50.0,A"）不应出现在上下文里
        # 我们检查没有完整的 CSV 数据行（3个字段全都数值）
        raw = p.read_text()
        # 取第一行数据（非表头）
        data_line = raw.split("\n")[1]
        assert data_line not in ctx

    def test_text_file_goes_to_excerpt(self, tmp_path):
        p = _make_text(tmp_path, content="# 研究笔记\n\n这是测试内容。\n" * 3)
        ctx, errors = process_message(f"看看 {p}", cwd=tmp_path)
        assert ctx  # 有注入内容
        assert "研究笔记" in ctx
        assert errors == []

    def test_missing_file_csv_gives_error(self, tmp_path):
        missing = tmp_path / "ghost.csv"
        ctx, errors = process_message(f"分析 {missing}", cwd=tmp_path)
        assert ctx == ""
        assert any("ghost.csv" in e for e in errors)

    def test_missing_file_text_gives_error(self, tmp_path):
        missing = tmp_path / "notes.md"
        ctx, errors = process_message(f"看看 {missing}", cwd=tmp_path)
        assert any("notes.md" in e for e in errors)

    def test_no_paths_returns_empty(self, tmp_path):
        ctx, errors = process_message("这是一个普通问题，没有路径", cwd=tmp_path)
        assert ctx == ""
        assert errors == []

    def test_original_file_not_modified(self, tmp_path):
        p = _make_csv(tmp_path)
        original = p.read_bytes()
        process_message(f"分析 {p}", cwd=tmp_path)
        assert p.read_bytes() == original  # 原始文件未被修改

    def test_multiple_files_both_injected(self, tmp_path):
        p1 = _make_csv(tmp_path, "scores.csv")
        p2 = _make_text(tmp_path, "notes.txt", content="研究备注")
        ctx, errors = process_message(f"对比 {p1} 和 {p2}", cwd=tmp_path)
        assert "<data_file" in ctx
        assert "研究备注" in ctx
        assert errors == []

    def test_relative_path_resolved(self, tmp_path):
        p = _make_csv(tmp_path)
        ctx, errors = process_message(f"分析 ./data.csv", cwd=tmp_path)
        assert "<data_file" in ctx
        assert errors == []

    def test_quoted_path_with_spaces(self, tmp_path):
        p = tmp_path / "my data file.csv"
        _make_csv(tmp_path, "my data file.csv")
        ctx, errors = process_message(f'分析 "{p}"', cwd=tmp_path)
        assert "<data_file" in ctx

    def test_nonexistent_no_extension_silently_skipped(self, tmp_path):
        # 不存在的无扩展名"路径"（如 /psychology）应该安静跳过，不报错
        ctx, errors = process_message("/nonexistent_no_ext 是什么", cwd=tmp_path)
        assert ctx == ""
        # 没有已知后缀 → 不应有错误提示
        assert len(errors) == 0


# ---------------------------------------------------------------------------
# _is_num
# ---------------------------------------------------------------------------

class TestIsNum:
    @pytest.mark.parametrize("s", ["3.14", "0", "-1", "1e5", "42"])
    def test_numeric(self, s):
        assert _is_num(s)

    @pytest.mark.parametrize("s", ["hello", "", "1,2", "NA", "nan"])
    def test_non_numeric(self, s):
        assert not _is_num(s)


# ---------------------------------------------------------------------------
# 数据保护铁律
# ---------------------------------------------------------------------------

class TestPrivacyInvariant:
    def test_large_csv_metadata_only(self, tmp_path):
        """大 CSV 也只注入元数据，不塞原始行。"""
        p = _make_csv(tmp_path, rows=1000)
        ctx, _ = process_message(f"分析 {p}", cwd=tmp_path)
        # 原始数据行（"1,50.0,A"）不在上下文
        raw_lines = p.read_text().split("\n")[1:4]
        for line in raw_lines:
            if line.strip():
                assert line.strip() not in ctx

    def test_tsv_classified_as_data(self, tmp_path):
        p = tmp_path / "data.tsv"
        with p.open("w", newline="", encoding="utf-8") as f:
            f.write("a\tb\tc\n1\t2\t3\n4\t5\t6\n")
        ctx, errors = process_message(f"看 {p}", cwd=tmp_path)
        assert "<data_file" in ctx
        assert errors == []
