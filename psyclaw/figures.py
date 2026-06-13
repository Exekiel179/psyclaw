"""psyclaw.figures — 统一图表主题层 (E-1)

所有子技能出图走同一入口，实施 figure_style.yaml 的 APA7/nature/frontiers 预设
与诚实性门禁（y 轴归零、误差棒标注、色盲友好调色板）。

公开接口:
  apply_style(name)          contextmanager — 应用 matplotlib rcParams
  honesty_check(spec)        → {passed, issues, warnings} 检查图表诚实性
  list_styles()              → [{name, desc}, ...] 列出预设风格
  okabe_ito_palette(n)       → [hex, ...] 截取 Okabe-Ito 调色板前 n 色
  theme_spec(name)           → dict 风格配置字典

降级策略:
  matplotlib 不可用 → apply_style 为空 contextmanager，其余函数正常工作。
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any, Iterator

FIGSTYLE_PATH = Path(__file__).parent / "gates" / "figure_style.yaml"

# ---------------------------------------------------------------------------
# Okabe-Ito 色盲友好调色板（8 色，已被 Nature/APA 推荐）
# ---------------------------------------------------------------------------

OKABE_ITO = [
    "#E69F00",  # orange
    "#56B4E9",  # sky blue
    "#009E73",  # bluish green
    "#F0E442",  # yellow
    "#0072B2",  # blue
    "#D55E00",  # vermillion
    "#CC79A7",  # reddish purple
    "#000000",  # black
]


def okabe_ito_palette(n: int = 8) -> list[str]:
    """返回 Okabe-Ito 调色板前 n 色（n > 8 则循环）。"""
    n = max(1, n)
    if n <= len(OKABE_ITO):
        return OKABE_ITO[:n]
    reps, rem = divmod(n, len(OKABE_ITO))
    return OKABE_ITO * reps + OKABE_ITO[:rem]


# ---------------------------------------------------------------------------
# 内置风格预设（figure_style.yaml 的 Python 镜像，零依赖可用）
# ---------------------------------------------------------------------------

_BUILTIN_PRESETS: dict[str, dict[str, Any]] = {
    "apa7": {
        "font_family": ["Arial", "Helvetica", "sans-serif"],
        "min_font_pt": 8,
        "spines": ["left", "bottom"],
        "grid": False,
        "background": "white",
        "desc": "APA 7th edition — 无右/上轴，白底，无网格",
    },
    "nature": {
        "font_family": ["Arial", "sans-serif"],
        "min_font_pt": 7,
        "spines": ["left", "bottom"],
        "grid": False,
        "background": "white",
        "desc": "Nature 系列 — 极简，字号≥7pt",
    },
    "frontiers": {
        "font_family": ["Arial", "sans-serif"],
        "min_font_pt": 8,
        "spines": ["left", "bottom"],
        "grid": False,
        "background": "white",
        "desc": "Frontiers — 与 nature 近似，要求 tiff/pdf 格式",
    },
    "minimal": {
        "font_family": ["Arial", "sans-serif"],
        "min_font_pt": 8,
        "spines": ["bottom"],
        "grid": False,
        "background": "white",
        "desc": "极简 — 仅底轴",
    },
}

_DEFAULT_STYLE = "apa7"


# ---------------------------------------------------------------------------
# 从 figure_style.yaml 读取（可选；不可读时回落内置）
# ---------------------------------------------------------------------------

def _load_figstyle() -> dict[str, Any]:
    """简单解析 figure_style.yaml（不依赖 pyyaml）。

    只解析顶层 key: value 和二/三级嵌套（空格缩进 2/4），
    列表用 [a, b, c] 行内格式。缺失或格式错误时返回 {}。
    """
    if not FIGSTYLE_PATH.exists():
        return {}
    try:
        lines = FIGSTYLE_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}

    def _coerce(s: str) -> Any:
        s = s.strip()
        if s.lower() == "true":
            return True
        if s.lower() == "false":
            return False
        try:
            return int(s)
        except ValueError:
            pass
        try:
            return float(s)
        except ValueError:
            pass
        if s.startswith("[") and s.endswith("]"):
            return [v.strip() for v in s[1:-1].split(",") if v.strip()]
        return s.strip("'\"")

    root: dict = {}
    stack: list[tuple[int, dict]] = [(0, root)]

    for line in lines:
        raw = line.split("#", 1)[0].rstrip()
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip())
        st = raw.strip()
        if ":" not in st:
            continue
        k, _, v = st.partition(":")
        k = k.strip()
        v = v.strip()
        # pop stack frames deeper than current indent
        while len(stack) > 1 and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        if v:
            parent[k] = _coerce(v)
        else:
            child: dict = {}
            parent[k] = child
            stack.append((indent + 2, child))

    return root


_FIGSTYLE_CACHE: dict[str, Any] | None = None


def _figstyle() -> dict[str, Any]:
    global _FIGSTYLE_CACHE
    if _FIGSTYLE_CACHE is None:
        _FIGSTYLE_CACHE = _load_figstyle()
    return _FIGSTYLE_CACHE


# ---------------------------------------------------------------------------
# theme_spec — 读取风格配置
# ---------------------------------------------------------------------------

def theme_spec(name: str | None = None) -> dict[str, Any]:
    """返回命名风格的配置字典（合并 yaml 覆盖 + 内置默认）。"""
    style_name = name or _DEFAULT_STYLE
    base = dict(_BUILTIN_PRESETS.get(style_name, _BUILTIN_PRESETS[_DEFAULT_STYLE]))
    # yaml 中的覆盖
    yaml_styles = _figstyle().get("styles", {})
    if isinstance(yaml_styles, dict) and style_name in yaml_styles:
        yspec = yaml_styles[style_name]
        if isinstance(yspec, dict):
            base.update(yspec)
    return base


# ---------------------------------------------------------------------------
# list_styles — 列出可用风格
# ---------------------------------------------------------------------------

def list_styles() -> list[dict[str, str]]:
    """列出已知风格（内置 + yaml 中额外定义的）。"""
    names = set(_BUILTIN_PRESETS.keys())
    yaml_styles = _figstyle().get("styles", {})
    if isinstance(yaml_styles, dict):
        names |= set(yaml_styles.keys())
    out = []
    for n in sorted(names):
        spec = _BUILTIN_PRESETS.get(n, {})
        out.append({"name": n, "desc": spec.get("desc", ""), "default": n == _DEFAULT_STYLE})
    return out


# ---------------------------------------------------------------------------
# apply_style — matplotlib rcParams 上下文管理器
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def apply_style(name: str | None = None) -> Iterator[None]:
    """应用指定风格的 matplotlib rcParams。

    matplotlib 不可用时静默跳过（不报错），方便无可视化环境下测试。

    用法:
        with psyclaw.figures.apply_style("apa7"):
            fig, ax = plt.subplots()
            ax.bar(...)
    """
    try:
        import matplotlib as mpl
        from matplotlib.cycler import cycler as mpl_cycler
    except ImportError:  # matplotlib 未安装 → 静默降级
        yield
        return

    spec = theme_spec(name)
    spines = spec.get("spines", ["left", "bottom"])
    fonts = spec.get("font_family", ["Arial", "Helvetica", "sans-serif"])
    font_size = spec.get("min_font_pt", 10)

    rc: dict[str, Any] = {
        "font.family": "sans-serif",
        "font.sans-serif": fonts,
        "font.size": font_size,
        "axes.labelsize": font_size,
        "xtick.labelsize": font_size,
        "ytick.labelsize": font_size,
        "axes.titlesize": font_size + 1,
        "axes.spines.top": "top" in spines,
        "axes.spines.right": "right" in spines,
        "axes.spines.bottom": "bottom" in spines,
        "axes.spines.left": "left" in spines,
        "axes.grid": spec.get("grid", False),
        "figure.facecolor": spec.get("background", "white"),
        "axes.facecolor": spec.get("background", "white"),
        "axes.prop_cycle": mpl_cycler("color", OKABE_ITO),
    }

    with mpl.rc_context(rc):
        yield


# ---------------------------------------------------------------------------
# honesty_check — 图表诚实性核查（对应 FIG.honest 门禁）
# ---------------------------------------------------------------------------

def honesty_check(spec: dict[str, Any]) -> dict[str, Any]:
    """核查图表 sidecar spec 是否满足 FIG.honest 诚实性规则。

    spec 期望字段（均可选，缺失时视为未声明）:
      axis_from_zero:     bool   — y 轴从 0 起
      truncation_flagged: bool   — 截断时是否已标注
      error_bar_label:    str    — 误差棒标注文本（SD / SE / 95%CI 等）
      colorblind_safe:    bool   — 是否使用色盲友好调色板
      dual_axis:          bool   — 是否使用双坐标轴
      dual_axis_flagged:  bool   — 双坐标轴是否有说明

    返回 {passed, issues: [str], warnings: [str]}。
    issues 非空则 passed = False（对应 gate action: block）。
    """
    issues: list[str] = []
    warnings: list[str] = []

    # 1. y 轴归零 或 截断须标注
    axis_zero = spec.get("axis_from_zero")
    trunc_flagged = spec.get("truncation_flagged", False)
    if axis_zero is False and not trunc_flagged:
        issues.append(
            "axis_from_zero_or_flagged: y 轴未从零起，且未标注截断"
            "（须在图或图注中明确标注 y 轴起点不为 0）"
        )

    # 2. 误差棒须有含义标注
    error_label = spec.get("error_bar_label", "")
    if not error_label or not str(error_label).strip():
        issues.append(
            "error_bar_meaning: 误差棒缺少含义标注"
            "（须在图注或图例中注明 SD / SE / 95%CI 之一）"
        )

    # 3. 色盲友好
    if spec.get("colorblind_safe") is False:
        issues.append(
            "colorblind_safe: 调色板未通过色盲友好检查"
            "（推荐 Okabe-Ito / viridis；避免单靠红绿区分）"
        )

    # 4. 双坐标轴警告（warn 级）
    if spec.get("dual_axis", False) and not spec.get("dual_axis_flagged", False):
        warnings.append(
            "no_dual_axis_without_flag: 使用了双 y 轴但未注明含义"
            "（建议在图注中说明两轴所代表的变量及其单位）"
        )

    return {"passed": len(issues) == 0, "issues": issues, "warnings": warnings}


# ---------------------------------------------------------------------------
# write_figure_sidecar — 便捷写 sidecar JSON（供绘图代码调用）
# ---------------------------------------------------------------------------

def write_figure_sidecar(
    out_path: str | Path,
    *,
    axis_from_zero: bool = True,
    truncation_flagged: bool = False,
    error_bar_label: str = "",
    colorblind_safe: bool = True,
    dual_axis: bool = False,
    dual_axis_flagged: bool = False,
    extra: dict[str, Any] | None = None,
) -> Path:
    """写入图表诚实性 sidecar JSON，供 FIG.honest 门禁机器校验。

    返回写入的路径。
    """
    import json
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "axis_from_zero": axis_from_zero,
        "truncation_flagged": truncation_flagged,
        "error_bar_label": error_bar_label,
        "colorblind_safe": colorblind_safe,
        "dual_axis": dual_axis,
        "dual_axis_flagged": dual_axis_flagged,
    }
    if extra:
        data.update(extra)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# CLI helper — figures 命令
# ---------------------------------------------------------------------------

def figures_cli(argv: list[str] | None = None) -> int:
    """psyclaw figures 命令实现。"""
    import argparse
    import json

    parser = argparse.ArgumentParser(prog="psyclaw figures",
                                     description="图表主题层 — 风格预设 / 诚实性核查 / 调色板")
    parser.add_argument("--list-styles", action="store_true", help="列出所有内置风格预设")
    parser.add_argument("--style", default=None,
                        help="查看指定风格的配置（apa7 / nature / frontiers / minimal）")
    parser.add_argument("--check", default=None, metavar="SPEC.JSON",
                        help="对图表 sidecar JSON 跑 FIG.honest 诚实性核查")
    parser.add_argument("--palette", type=int, default=0, metavar="N",
                        help="打印 Okabe-Ito 调色板前 N 色（默认 8）")
    args = parser.parse_args(argv or [])

    any_action = False

    if args.list_styles:
        any_action = True
        print("已注册图表风格:")
        for s in list_styles():
            tag = " [默认]" if s["default"] else ""
            print(f"  {s['name']:<12}{tag}  {s['desc']}")

    if args.style:
        any_action = True
        spec = theme_spec(args.style)
        print(f"风格 [{args.style}] 配置:")
        print(json.dumps({k: v for k, v in spec.items() if k != "desc"},
                         ensure_ascii=False, indent=2))

    if args.check:
        any_action = True
        p = Path(args.check)
        if not p.exists():
            print(f"文件不存在: {args.check}")
            return 1
        try:
            spec = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"JSON 解析失败: {exc}")
            return 1
        result = honesty_check(spec)
        if result["passed"]:
            print("✓ FIG.honest 诚实性核查通过")
        else:
            print("✗ FIG.honest 诚实性核查 — 以下问题须修复:")
            for iss in result["issues"]:
                print(f"  ✗ {iss}")
        for w in result["warnings"]:
            print(f"  ⚠ {w}")
        return 0 if result["passed"] else 1

    n_pal = args.palette or 8
    if args.palette or not any_action:
        colors = okabe_ito_palette(n_pal)
        print(f"Okabe-Ito 调色板（前 {n_pal} 色，色盲友好）:")
        for i, c in enumerate(colors, 1):
            print(f"  {i:2d}  {c}")
        any_action = True

    if not any_action:
        parser.print_help()
    return 0
