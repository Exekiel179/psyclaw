"""M-4: 自定义量表测试 — 用户 YAML 放 .psyclaw/scales/ 与内置库合并。"""
from __future__ import annotations

import contextlib
import csv
import inspect
import io
import sys
import tempfile
from pathlib import Path

try:
    import pytest
except ModuleNotFoundError:
    class _Approx:
        def __init__(self, v, abs=1e-6, rel=None):
            self._v = v
            self._abs = abs
        def __eq__(self, other):
            return abs(other - self._v) <= self._abs
        def __repr__(self):
            return f"approx({self._v})"
    class pytest:  # type: ignore[no-redef]
        @staticmethod
        def approx(v, abs=1e-6, rel=None):
            return _Approx(v, abs=abs)

from psyclaw.psych.scales import (
    _user_scales_dir,
    _load_user_scales,
    list_scales,
    get_scale,
    print_scale,
    score_datafile,
)


# ---------------------------------------------------------------------------
# 辅助：在临时目录里建 .psyclaw/scales/
# ---------------------------------------------------------------------------

def _make_user_dir(tmp: Path) -> Path:
    d = tmp / ".psyclaw" / "scales"
    d.mkdir(parents=True)
    return d


SIMPLE_YAML = """\
- id: my-test-scale
  name: My Test Scale
  items: 3
  response: "1-5 Likert"
  subscales:
    Total: [1, 2, 3]
  reverse: [2]
  reliability_ref: "α ≈ .80"
  notes: "仅测试用"
"""

OVERRIDE_YAML = """\
- id: tipi
  name: TIPI Override
  items: 10
  response: "1-7"
  subscales:
    Extraversion: [1, 6]
    Agreeableness: [2, 7]
    Conscientiousness: [3, 8]
    EmotionalStability: [4, 9]
    Openness: [5, 10]
  reverse: [2, 4, 6, 8, 10]
  reliability_ref: "用户覆盖版本"
  notes: "override test"
"""

MULTI_SCALE_YAML = """\
- id: scale-a
  name: Scale A
  items: 4
  response: "1-5"
  subscales:
    Total: [1, 2, 3, 4]
  reverse: []

- id: scale-b
  name: Scale B
  items: 2
  response: "0-3"
  subscales:
    Total: [1, 2]
  reverse: [1]
"""

MALFORMED_YAML = "this is: not: valid: yaml\nbut _parse_scales is forgiving\n"


# ---------------------------------------------------------------------------
# _user_scales_dir
# ---------------------------------------------------------------------------

def test_user_scales_dir_default_is_cwd():
    d = _user_scales_dir()
    assert d == Path.cwd() / ".psyclaw" / "scales"


def test_user_scales_dir_custom():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        d = _user_scales_dir(p)
        assert d == p / ".psyclaw" / "scales"


# ---------------------------------------------------------------------------
# _load_user_scales — 目录不存在时返回空
# ---------------------------------------------------------------------------

def test_load_user_scales_no_dir():
    with tempfile.TemporaryDirectory() as tmp:
        scales = _load_user_scales(tmp)
        assert scales == []


# ---------------------------------------------------------------------------
# _load_user_scales — 加载单文件
# ---------------------------------------------------------------------------

def test_load_user_scales_single_file():
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_user_dir(Path(tmp))
        (d / "my_scale.yaml").write_text(SIMPLE_YAML, encoding="utf-8")
        scales = _load_user_scales(tmp)
    assert len(scales) == 1
    s = scales[0]
    assert s["id"] == "my-test-scale"
    assert s["name"] == "My Test Scale"
    assert s["items"] == "3"
    assert s["reverse"] == [2]
    assert s["_source"] == "my_scale.yaml"


# ---------------------------------------------------------------------------
# _load_user_scales — 多量表单文件
# ---------------------------------------------------------------------------

def test_load_user_scales_multi_in_one_file():
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_user_dir(Path(tmp))
        (d / "multi.yaml").write_text(MULTI_SCALE_YAML, encoding="utf-8")
        scales = _load_user_scales(tmp)
    ids = [s["id"] for s in scales]
    assert "scale-a" in ids
    assert "scale-b" in ids
    assert len(scales) == 2


# ---------------------------------------------------------------------------
# _load_user_scales — 多文件按文件名排序加载
# ---------------------------------------------------------------------------

def test_load_user_scales_multiple_files():
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_user_dir(Path(tmp))
        (d / "aaa.yaml").write_text(SIMPLE_YAML, encoding="utf-8")
        (d / "bbb.yaml").write_text(MULTI_SCALE_YAML, encoding="utf-8")
        scales = _load_user_scales(tmp)
    ids = [s["id"] for s in scales]
    assert "my-test-scale" in ids
    assert "scale-a" in ids
    assert "scale-b" in ids
    assert len(scales) == 3


# ---------------------------------------------------------------------------
# _load_user_scales — 损坏文件跳过，不影响其他文件
# ---------------------------------------------------------------------------

def test_load_user_scales_malformed_skipped():
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_user_dir(Path(tmp))
        # 仅写不含 `- id:` 的文件 → _parse_scales 返回空列表（不抛异常）
        (d / "bad.yaml").write_text("no_ids_here: true\n", encoding="utf-8")
        (d / "good.yaml").write_text(SIMPLE_YAML, encoding="utf-8")
        scales = _load_user_scales(tmp)
    assert len(scales) == 1
    assert scales[0]["id"] == "my-test-scale"


# ---------------------------------------------------------------------------
# list_scales — 用户量表追加到内置
# ---------------------------------------------------------------------------

def test_list_scales_includes_user():
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_user_dir(Path(tmp))
        (d / "my.yaml").write_text(SIMPLE_YAML, encoding="utf-8")
        scales = list_scales(tmp)
    ids = [s["id"] for s in scales]
    assert "my-test-scale" in ids
    assert "tipi" in ids           # 内置仍在
    assert "phq-9" in ids


# ---------------------------------------------------------------------------
# list_scales — 用户覆盖内置同 id
# ---------------------------------------------------------------------------

def test_list_scales_user_overrides_builtin():
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_user_dir(Path(tmp))
        (d / "override.yaml").write_text(OVERRIDE_YAML, encoding="utf-8")
        scales = list_scales(tmp)

    tipi_list = [s for s in scales if s["id"] == "tipi"]
    assert len(tipi_list) == 1          # 只有一个 tipi
    tipi = tipi_list[0]
    assert tipi["reliability_ref"] == "用户覆盖版本"
    assert tipi["_source"] == "override.yaml"


def test_list_scales_user_override_does_not_duplicate():
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_user_dir(Path(tmp))
        (d / "override.yaml").write_text(OVERRIDE_YAML, encoding="utf-8")
        scales = list_scales(tmp)
    tipi_count = sum(1 for s in scales if s["id"] == "tipi")
    assert tipi_count == 1


# ---------------------------------------------------------------------------
# list_scales — 内置量表有 _source == "built-in"
# ---------------------------------------------------------------------------

def test_builtin_scales_source_tag():
    with tempfile.TemporaryDirectory() as tmp:
        scales = list_scales(tmp)   # 空 tmp，无用户量表
    for s in scales:
        assert s.get("_source") == "built-in"


# ---------------------------------------------------------------------------
# get_scale — 找到内置
# ---------------------------------------------------------------------------

def test_get_scale_builtin():
    with tempfile.TemporaryDirectory() as tmp:
        s = get_scale("tipi", tmp)
    assert s is not None
    assert s["id"] == "tipi"


# ---------------------------------------------------------------------------
# get_scale — 找到用户自定义
# ---------------------------------------------------------------------------

def test_get_scale_user():
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_user_dir(Path(tmp))
        (d / "my.yaml").write_text(SIMPLE_YAML, encoding="utf-8")
        s = get_scale("my-test-scale", tmp)
    assert s is not None
    assert s["name"] == "My Test Scale"
    assert s["_source"] == "my.yaml"


# ---------------------------------------------------------------------------
# get_scale — 用户覆盖内置后 get_scale 返回用户版
# ---------------------------------------------------------------------------

def test_get_scale_override_returns_user_version():
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_user_dir(Path(tmp))
        (d / "override.yaml").write_text(OVERRIDE_YAML, encoding="utf-8")
        s = get_scale("tipi", tmp)
    assert s is not None
    assert s["reliability_ref"] == "用户覆盖版本"


# ---------------------------------------------------------------------------
# get_scale — 大小写不敏感
# ---------------------------------------------------------------------------

def test_get_scale_case_insensitive():
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_user_dir(Path(tmp))
        (d / "my.yaml").write_text(SIMPLE_YAML, encoding="utf-8")
        s1 = get_scale("My-Test-Scale", tmp)
        s2 = get_scale("MY-TEST-SCALE", tmp)
    assert s1 is not None and s1["id"] == "my-test-scale"
    assert s2 is not None and s2["id"] == "my-test-scale"


# ---------------------------------------------------------------------------
# get_scale — 未知量表返回 None
# ---------------------------------------------------------------------------

def test_get_scale_missing():
    with tempfile.TemporaryDirectory() as tmp:
        s = get_scale("nonexistent-xyz", tmp)
    assert s is None


# ---------------------------------------------------------------------------
# score_datafile — 使用用户自定义量表计分
# ---------------------------------------------------------------------------

def _make_csv(tmp: Path, n_items: int, values: list[list]) -> Path:
    p = tmp / "data.csv"
    headers = [f"Q{i}" for i in range(1, n_items + 1)]
    rows = [dict(zip(headers, row)) for row in values]
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        w.writerows(rows)
    return p


def test_score_datafile_with_user_scale():
    """用自定义 3 题量表（条目 2 反向）对两名被试计分。"""
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp)
        d = _make_user_dir(tp)
        (d / "my.yaml").write_text(SIMPLE_YAML, encoding="utf-8")

        # 量表 1-5，条目 2 反向 → reversed = 6 - raw
        # 被试1: [3, 4, 2] → reversed[2]=2 → [3, 2, 2] → total=7
        # 被试2: [5, 1, 5] → reversed[2]=5 → [5, 5, 5] → total=15
        csv_path = _make_csv(tp, 3, [[3, 4, 2], [5, 1, 5]])
        result = score_datafile(str(csv_path), "my-test-scale",
                                prefix="Q", project_dir=tmp)

    assert "error" not in result
    assert result["n"] == 2
    assert result["scale"]["id"] == "my-test-scale"

    p1 = result["participants"][0]
    assert p1["items"][2] == pytest.approx(2.0)   # 6-4
    assert p1["total"] == pytest.approx(7.0)

    p2 = result["participants"][1]
    assert p2["items"][2] == pytest.approx(5.0)   # 6-1
    assert p2["total"] == pytest.approx(15.0)


def test_score_datafile_unknown_scale_with_user_dir():
    """用户目录里没有 xyz 量表 → 报错列出可用量表（含用户量表）。"""
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp)
        d = _make_user_dir(tp)
        (d / "my.yaml").write_text(SIMPLE_YAML, encoding="utf-8")
        csv_path = _make_csv(tp, 1, [[1]])
        result = score_datafile(str(csv_path), "xyz-unknown", project_dir=tmp)

    assert "error" in result
    assert "my-test-scale" in result["error"]   # 列出了用户量表


# ---------------------------------------------------------------------------
# print_scale — 输出包含用户量表且显示来源标签（烟雾测试）
# ---------------------------------------------------------------------------

def _capture(fn, *args, **kwargs) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args, **kwargs)
    return buf.getvalue()


def test_print_scale_listing_shows_user():
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_user_dir(Path(tmp))
        (d / "my.yaml").write_text(SIMPLE_YAML, encoding="utf-8")
        out = _capture(print_scale, project_dir=tmp)
    assert "my-test-scale" in out
    assert "用户:my.yaml" in out


def test_print_scale_detail_shows_source():
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_user_dir(Path(tmp))
        (d / "my.yaml").write_text(SIMPLE_YAML, encoding="utf-8")
        out = _capture(print_scale, "my-test-scale", project_dir=tmp)
    assert "My Test Scale" in out
    assert "来源" in out
    assert "my.yaml" in out


def test_print_scale_builtin_no_source_tag():
    with tempfile.TemporaryDirectory() as tmp:
        out = _capture(print_scale, "tipi", project_dir=tmp)
    assert "TIPI" in out or "Ten-Item" in out
    assert "来源" not in out   # 内置不显示来源行


# ---------------------------------------------------------------------------
# 边界：用户目录存在但为空 → 只有内置
# ---------------------------------------------------------------------------

def test_empty_user_dir_only_builtins():
    with tempfile.TemporaryDirectory() as tmp:
        _make_user_dir(Path(tmp))   # 空目录
        scales = list_scales(tmp)
    builtin_scales = list_scales(Path(tmp) / "__nonexistent__")
    # 两者量表 id 集合相同
    assert {s["id"] for s in scales} == {s["id"] for s in builtin_scales}


# ---------------------------------------------------------------------------
# Self-run block (no pytest needed)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in fns:
        sig = inspect.signature(fn)
        try:
            fn()
            print(f"  ✓ {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  ✗ {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ✗ {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
