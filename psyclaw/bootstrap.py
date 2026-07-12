"""能力检测与选装(stdlib only)。

理念:核心零依赖开箱即用;增强能力按需选装,装什么由用户决定。
- 开源依赖按功能分组(stats/eeg/viz/full),检测缺失 → 征求同意 pip --user 安装
- 商业软件(SPSS/Mplus/Stata/R)只检测,不分发;装了就启用执行,没装则降级
  (SPSS/MNE 的语法/脚本生成始终可用,不依赖本地安装)
- 内置 MCP(mne/spss 服务器)随包自带,零配置;`psyclaw mcp --serve` 即起

`psyclaw setup` 走交互选装;`psyclaw doctor` 显示能力矩阵。
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys

# 功能组 → (说明, [pip 包名(import 名)])
# stats 组为**核心默认**:pingouin 一次给出统计量+效应量+CI+功效+BF,满足 PSYCLAW 质量检查。
DEP_GROUPS: dict = {
    "stats": ("【核心·默认装】统计主路径:pingouin(心理学一次出全)+ scipy/statsmodels",
              [("pingouin", "pingouin"), ("pandas", "pandas"), ("numpy", "numpy"),
               ("scipy", "scipy"), ("statsmodels", "statsmodels")]),
    "viz": ("出版级图表(APA7 主题)",
            [("matplotlib", "matplotlib"), ("seaborn", "seaborn")]),
    "eeg": ("EEG/MEG/ERP 分析(MNE MCP 真跑)",
            [("mne", "mne")]),
    "full": ("交互增强(更佳 REPL/网络)",
             [("rich", "rich"), ("prompt_toolkit", "prompt_toolkit"),
              ("requests", "requests")]),
    "embed": ("本地语义嵌入(召回升级:model2vec 静态多语言模型,纯 numpy 无 torch,"
              "首次使用自动下载权重后离线可用;未装时用内置哈希向量兜底)",
              [("model2vec", "model2vec"), ("numpy", "numpy")]),
}

# 商业/外部软件:只检测二进制,不安装
EXTERNAL_BINS: dict = {
    "R": (["Rscript"], "lavaan/lme4/psych —— SEM/多层/ω 信度"),
    "SPSS": (["stats", "statisticsb"], "SPSS 批处理执行(语法生成不需要它)"),
    "Mplus": (["mplus"], "SEM/潜变量/混合模型"),
    "Stata": (["stata", "stata-mp", "stata-se"], "面板/计量"),
}


def _has_module(import_name: str) -> bool:
    try:
        return importlib.util.find_spec(import_name) is not None
    except (ImportError, ValueError):
        return False


def detect() -> dict:
    """返回能力矩阵。"""
    groups = {}
    for g, (desc, pkgs) in DEP_GROUPS.items():
        present = [imp for _, imp in pkgs if _has_module(imp)]
        groups[g] = {"desc": desc, "have": present,
                     "missing": [(pip, imp) for pip, imp in pkgs if not _has_module(imp)],
                     "ready": len(present) == len(pkgs)}
    bins = {}
    for name, (cands, desc) in EXTERNAL_BINS.items():
        found = next((c for c in cands if shutil.which(c)), None)
        bins[name] = {"desc": desc, "path": found, "ready": bool(found)}
    return {"groups": groups, "bins": bins}


def _pip_install(pip_names: list) -> bool:
    cmd = [sys.executable, "-m", "pip", "install", "--user", "--upgrade", *pip_names]
    print("  运行:", " ".join(cmd))
    try:
        r = subprocess.run(cmd, timeout=600)
        return r.returncode == 0
    except Exception as exc:  # noqa: BLE001
        print(f"  安装失败:{exc}")
        return False


def print_matrix() -> None:
    from psyclaw import ui
    d = detect()
    print(ui.accent("开源能力组:"))
    for g, info in d["groups"].items():
        mark = ui.ok("就绪 ✓") if info["ready"] else ui.warn(f"缺 {len(info['missing'])} 个")
        print(f"  {g:<6} {mark}  " + ui.dim(info["desc"]))
        if info["missing"]:
            print("         " + ui.dim("缺: " + ", ".join(p for p, _ in info["missing"])))
    print(ui.accent("\n外部软件(选装,只检测不分发):"))
    for name, info in d["bins"].items():
        mark = ui.ok(f"✓ {info['path']}") if info["ready"] else ui.dim("未检测到")
        print(f"  {name:<7} {mark}  " + ui.dim(info["desc"]))
    print(ui.accent("\n内置 MCP(随包自带,零配置):"))
    print("  mne / spss —— `psyclaw mcp --serve mne|spss`,或挂到 Claude Desktop")


def run_setup(non_interactive: bool = False, groups: list | None = None) -> int:
    """交互选装。groups 指定要装的组;非交互+无 groups 则只显示矩阵。"""
    from psyclaw import ui
    print(ui.title("PsyClaw setup — 能力选装"))
    print(ui.rule())
    print_matrix()
    d = detect()
    missing_groups = [g for g, i in d["groups"].items() if not i["ready"]]
    if not missing_groups:
        print(ui.ok("\n所有能力组已就绪,开箱即用。"))
        return 0

    # stats 是核心组:pingouin 默认装(非交互也装,除非 --groups 明确指定别的)
    if "stats" in missing_groups and not groups:
        print(ui.accent("\n核心组 stats(含 pingouin)缺失,默认安装中…"))
        pkgs = [p for p, _ in d["groups"]["stats"]["missing"]]
        ok = _pip_install(pkgs)
        print(ui.ok("  ✓ stats 核心已装(pingouin 就绪)") if ok else ui.err("  ✗ stats 安装失败,可手动 pip install pingouin"))
        missing_groups = [g for g in missing_groups if g != "stats"]
        if not missing_groups:
            return 0 if ok else 1

    if non_interactive:
        if not groups:
            print(ui.dim("\n(非交互模式,未指定 --groups,不安装。)"))
            return 0
        targets = groups
    else:
        print(ui.warn(f"\n缺失组:{', '.join(missing_groups)}"))
        print(ui.dim("选装哪些?(逗号分隔组名,或 all / 回车跳过)"))
        try:
            sel = input("  > ").strip().lower()
        except EOFError:
            sel = ""
        if not sel:
            print(ui.dim("跳过安装。核心功能不受影响;装了对应组后再用增强功能。"))
            return 0
        targets = missing_groups if sel == "all" else [s.strip() for s in sel.split(",")]

    ok_all = True
    for g in targets:
        info = d["groups"].get(g)
        if not info or info["ready"]:
            continue
        pkgs = [p for p, _ in info["missing"]]
        print(ui.accent(f"\n安装组 {g}: {', '.join(pkgs)}"))
        ok = _pip_install(pkgs)
        print(ui.ok(f"  ✓ {g} 安装完成") if ok else ui.err(f"  ✗ {g} 安装失败"))
        ok_all = ok_all and ok
    print(ui.dim("\n运行 `psyclaw doctor` 复检。"))
    return 0 if ok_all else 1
