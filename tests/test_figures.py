"""E-1 图表主题层测试 — figures.py / FIG.honest 门禁 / CLI。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.figures import (  # noqa: E402
    OKABE_ITO,
    honesty_check,
    list_styles,
    okabe_ito_palette,
    theme_spec,
    write_figure_sidecar,
    figures_cli,
)
from psyclaw.gates.checker import (  # noqa: E402
    REQUIREMENT_CHECKS,
    check_artifact,
    load_rules,
)


# ---------------------------------------------------------------------------
# Okabe-Ito 调色板
# ---------------------------------------------------------------------------

class TestOkabeItoPalette:
    def test_default_8(self):
        pal = okabe_ito_palette()
        assert len(pal) == 8

    def test_all_hex(self):
        for c in okabe_ito_palette(8):
            assert c.startswith("#") and len(c) == 7

    def test_n_less_than_8(self):
        pal = okabe_ito_palette(3)
        assert len(pal) == 3
        assert pal == OKABE_ITO[:3]

    def test_n_greater_than_8_cycles(self):
        pal = okabe_ito_palette(10)
        assert len(pal) == 10
        assert pal[:8] == OKABE_ITO
        assert pal[8:] == OKABE_ITO[:2]

    def test_n_zero_returns_empty(self):
        # n=0 → max(1,0)=1 → 返回1色
        pal = okabe_ito_palette(0)
        assert len(pal) == 1

    def test_no_red_green_only(self):
        # Okabe-Ito 无纯红 (#FF0000) 和纯绿 (#00FF00) 对
        assert "#FF0000" not in OKABE_ITO
        assert "#00FF00" not in OKABE_ITO


# ---------------------------------------------------------------------------
# theme_spec
# ---------------------------------------------------------------------------

class TestThemeSpec:
    def test_apa7_defaults(self):
        spec = theme_spec("apa7")
        assert "left" in spec["spines"]
        assert "bottom" in spec["spines"]
        assert "top" not in spec["spines"]
        assert spec["grid"] is False

    def test_nature_min_font(self):
        spec = theme_spec("nature")
        assert spec["min_font_pt"] <= 8

    def test_frontiers(self):
        spec = theme_spec("frontiers")
        assert "left" in spec.get("spines", [])

    def test_minimal_only_bottom(self):
        spec = theme_spec("minimal")
        assert spec["spines"] == ["bottom"]

    def test_unknown_falls_back_to_apa7(self):
        spec = theme_spec("nonexistent_style")
        assert "left" in spec["spines"]

    def test_none_uses_default(self):
        spec = theme_spec(None)
        assert spec == theme_spec("apa7")


# ---------------------------------------------------------------------------
# list_styles
# ---------------------------------------------------------------------------

class TestListStyles:
    def test_returns_list(self):
        styles = list_styles()
        assert isinstance(styles, list)
        assert len(styles) >= 4

    def test_contains_apa7(self):
        names = {s["name"] for s in list_styles()}
        assert "apa7" in names

    def test_apa7_is_default(self):
        defaults = [s for s in list_styles() if s.get("default")]
        assert len(defaults) == 1
        assert defaults[0]["name"] == "apa7"

    def test_each_has_name_and_desc(self):
        for s in list_styles():
            assert "name" in s
            assert "desc" in s


# ---------------------------------------------------------------------------
# honesty_check
# ---------------------------------------------------------------------------

class TestHonestyCheck:
    def _good_spec(self) -> dict:
        return {
            "axis_from_zero": True,
            "truncation_flagged": False,
            "error_bar_label": "95%CI",
            "colorblind_safe": True,
            "dual_axis": False,
        }

    def test_clean_spec_passes(self):
        r = honesty_check(self._good_spec())
        assert r["passed"] is True
        assert r["issues"] == []
        assert r["warnings"] == []

    def test_axis_not_zero_unflagged_blocks(self):
        spec = self._good_spec()
        spec["axis_from_zero"] = False
        spec["truncation_flagged"] = False
        r = honesty_check(spec)
        assert r["passed"] is False
        assert any("axis_from_zero_or_flagged" in iss for iss in r["issues"])

    def test_axis_not_zero_but_flagged_passes(self):
        spec = self._good_spec()
        spec["axis_from_zero"] = False
        spec["truncation_flagged"] = True
        r = honesty_check(spec)
        assert r["passed"] is True

    def test_missing_error_bar_label_blocks(self):
        spec = self._good_spec()
        spec["error_bar_label"] = ""
        r = honesty_check(spec)
        assert r["passed"] is False
        assert any("error_bar_meaning" in iss for iss in r["issues"])

    def test_whitespace_error_bar_label_blocks(self):
        spec = self._good_spec()
        spec["error_bar_label"] = "   "
        r = honesty_check(spec)
        assert r["passed"] is False

    def test_se_label_passes(self):
        spec = self._good_spec()
        spec["error_bar_label"] = "SE"
        r = honesty_check(spec)
        assert r["passed"] is True

    def test_sd_label_passes(self):
        spec = self._good_spec()
        spec["error_bar_label"] = "SD"
        r = honesty_check(spec)
        assert r["passed"] is True

    def test_not_colorblind_safe_blocks(self):
        spec = self._good_spec()
        spec["colorblind_safe"] = False
        r = honesty_check(spec)
        assert r["passed"] is False
        assert any("colorblind_safe" in iss for iss in r["issues"])

    def test_colorblind_safe_true_passes(self):
        spec = self._good_spec()
        spec["colorblind_safe"] = True
        r = honesty_check(spec)
        assert r["passed"] is True

    def test_dual_axis_without_flag_warns(self):
        spec = self._good_spec()
        spec["dual_axis"] = True
        spec["dual_axis_flagged"] = False
        r = honesty_check(spec)
        assert r["passed"] is True  # 仅 warn 不 block
        assert len(r["warnings"]) == 1

    def test_dual_axis_flagged_no_warn(self):
        spec = self._good_spec()
        spec["dual_axis"] = True
        spec["dual_axis_flagged"] = True
        r = honesty_check(spec)
        assert r["warnings"] == []

    def test_multiple_issues_collected(self):
        spec = {
            "axis_from_zero": False,
            "truncation_flagged": False,
            "error_bar_label": "",
            "colorblind_safe": False,
        }
        r = honesty_check(spec)
        assert r["passed"] is False
        assert len(r["issues"]) == 3

    def test_missing_keys_treat_as_safe(self):
        # axis_from_zero 缺失 → 视为 True（不触发）
        # error_bar_label 缺失 → 视为 "" → 触发
        r = honesty_check({"colorblind_safe": True})
        assert any("error_bar_meaning" in iss for iss in r["issues"])

    def test_axis_from_zero_none_not_blocked(self):
        # axis_from_zero=None 或缺失视为未截断（不触发）
        spec = {"error_bar_label": "95%CI", "colorblind_safe": True}
        r = honesty_check(spec)
        assert r["passed"] is True


# ---------------------------------------------------------------------------
# write_figure_sidecar
# ---------------------------------------------------------------------------

class TestWriteFigureSidecar:
    def test_writes_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_figure_sidecar(
                Path(tmp) / "fig.json",
                axis_from_zero=True,
                error_bar_label="95%CI",
                colorblind_safe=True,
            )
            data = json.loads(p.read_text())
            assert data["axis_from_zero"] is True
            assert data["error_bar_label"] == "95%CI"
            assert data["colorblind_safe"] is True

    def test_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_figure_sidecar(
                Path(tmp) / "sub" / "dir" / "fig.json",
                error_bar_label="SD",
                colorblind_safe=True,
            )
            assert p.exists()

    def test_extra_fields_included(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_figure_sidecar(
                Path(tmp) / "fig.json",
                error_bar_label="SE",
                colorblind_safe=True,
                extra={"caption_n": 120, "test_stat": "F(2,117)=4.32"},
            )
            data = json.loads(p.read_text())
            assert data["caption_n"] == 120
            assert "test_stat" in data


# ---------------------------------------------------------------------------
# FIG.honest 门禁 — checker.py 集成
# ---------------------------------------------------------------------------

class TestFigHonestGate:
    def test_requirement_checks_registered(self):
        for req in ("axis_from_zero_or_flagged", "error_bar_meaning", "colorblind_safe"):
            assert req in REQUIREMENT_CHECKS, f"未注册: {req}"

    def test_fig_gate_in_rules(self):
        rules = load_rules()
        gate_ids = {g["id"] for g in rules}
        assert "FIG.honest" in gate_ids

    def _write_sidecar(self, tmp: str, data: dict) -> str:
        p = Path(tmp) / "figure_sidecar.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return str(p)

    def test_passing_figure_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_sidecar(tmp, {
                "axis_from_zero": True,
                "error_bar_label": "95%CI",
                "colorblind_safe": True,
            })
            result = check_artifact(path, "figure")
            assert result["passed"] is True
            blocking_ids = {b["gate"] for b in result["blocking"]}
            assert "FIG.honest" not in blocking_ids

    def test_blocking_figure_sidecar_no_error_bar(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_sidecar(tmp, {
                "axis_from_zero": True,
                "error_bar_label": "",
                "colorblind_safe": True,
            })
            result = check_artifact(path, "figure")
            assert result["passed"] is False
            blocking_reqs = {b["requirement"] for b in result["blocking"]}
            assert "error_bar_meaning" in blocking_reqs

    def test_blocking_figure_axis_truncated_unflagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_sidecar(tmp, {
                "axis_from_zero": False,
                "truncation_flagged": False,
                "error_bar_label": "SD",
                "colorblind_safe": True,
            })
            result = check_artifact(path, "figure")
            assert result["passed"] is False
            blocking_reqs = {b["requirement"] for b in result["blocking"]}
            assert "axis_from_zero_or_flagged" in blocking_reqs

    def test_passing_with_truncation_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_sidecar(tmp, {
                "axis_from_zero": False,
                "truncation_flagged": True,
                "error_bar_label": "95%CI",
                "colorblind_safe": True,
            })
            result = check_artifact(path, "figure")
            fig_blocking = [b for b in result["blocking"] if b["gate"] == "FIG.honest"]
            assert fig_blocking == []

    def test_not_colorblind_safe_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_sidecar(tmp, {
                "axis_from_zero": True,
                "error_bar_label": "SE",
                "colorblind_safe": False,
            })
            result = check_artifact(path, "figure")
            assert result["passed"] is False
            blocking_reqs = {b["requirement"] for b in result["blocking"]}
            assert "colorblind_safe" in blocking_reqs

    def test_stat_kind_does_not_trigger_fig_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_sidecar(tmp, {
                "axis_from_zero": False,
                "error_bar_label": "",
                "colorblind_safe": False,
            })
            result = check_artifact(path, "stat")
            # FIG.honest 的 trigger 是 figure_output，stat kind 不包含
            blocking_ids = {b["gate"] for b in result["blocking"]}
            assert "FIG.honest" not in blocking_ids


# ---------------------------------------------------------------------------
# apply_style — 仅测试不崩溃（matplotlib 可能未安装）
# ---------------------------------------------------------------------------

class TestApplyStyle:
    def test_apply_style_no_crash(self):
        from psyclaw.figures import apply_style
        # 不管 matplotlib 是否安装，都不应抛出异常
        with apply_style("apa7"):
            pass

    def test_apply_style_nature(self):
        from psyclaw.figures import apply_style
        with apply_style("nature"):
            pass

    def test_apply_style_unknown_no_crash(self):
        from psyclaw.figures import apply_style
        with apply_style("unknown_style_xyz"):
            pass


# ---------------------------------------------------------------------------
# figures_cli
# ---------------------------------------------------------------------------

class TestFiguresCli:
    def test_list_styles_exits_0(self, capsys):
        rc = figures_cli(["--list-styles"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "apa7" in out

    def test_style_query_exits_0(self, capsys):
        rc = figures_cli(["--style", "apa7"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "spines" in out

    def test_palette_exits_0(self, capsys):
        rc = figures_cli(["--palette", "5"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "#" in out

    def test_check_passing_json(self, capsys):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "fig.json"
            p.write_text(json.dumps({
                "axis_from_zero": True,
                "error_bar_label": "95%CI",
                "colorblind_safe": True,
            }))
            rc = figures_cli(["--check", str(p)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "通过" in out or "passed" in out.lower()

    def test_check_failing_json(self, capsys):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "fig.json"
            p.write_text(json.dumps({
                "axis_from_zero": False,
                "truncation_flagged": False,
                "error_bar_label": "",
                "colorblind_safe": False,
            }))
            rc = figures_cli(["--check", str(p)])
        assert rc == 1

    def test_check_missing_file(self):
        rc = figures_cli(["--check", "/nonexistent/path/fig.json"])
        assert rc == 1

    def test_no_args_shows_palette(self, capsys):
        rc = figures_cli([])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Okabe" in out or "#" in out


# ---------------------------------------------------------------------------
# 自跑块（不依赖 pytest 命令，可用 python tests/test_figures.py 直接验证）
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import io
    import traceback

    # capsys 替代：捕获 stdout（readouterr 在 with 块内即可使用）
    class _CapSys:
        def __init__(self):
            self._sio = None
            self._old = None
        def __enter__(self):
            self._old = sys.stdout
            self._sio = io.StringIO()
            sys.stdout = self._sio
            return self
        def __exit__(self, *_):
            sys.stdout = self._old
        def readouterr(self):
            class _R:
                pass
            r = _R()
            r.out = self._sio.getvalue() if self._sio else ""
            return r

    # 注入 capsys 替代
    import types

    def _inject_capsys(fn, inst):
        import inspect
        sig = inspect.signature(fn)
        if "capsys" in sig.parameters:
            cap = _CapSys()
            def wrapped():
                with cap:
                    fn(cap)
            return wrapped
        return fn

    _SUITES = [
        TestOkabeItoPalette,
        TestThemeSpec,
        TestListStyles,
        TestHonestyCheck,
        TestWriteFigureSidecar,
        TestFigHonestGate,
        TestApplyStyle,
        TestFiguresCli,
    ]

    passed = failed = 0
    for suite_cls in _SUITES:
        suite = suite_cls()
        for name in sorted(m for m in dir(suite_cls) if m.startswith("test_")):
            fn = getattr(suite, name)
            fn = _inject_capsys(fn, suite)
            try:
                fn()
                passed += 1
                print(f"  PASS  {suite_cls.__name__}.{name}")
            except Exception as exc:
                failed += 1
                print(f"  FAIL  {suite_cls.__name__}.{name}")
                traceback.print_exc()

    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
