"""一键配置缺失的基础环境 —— `psyclaw setup --env`(v0.9 feat-051)。

诊断跑 psyclaw 所需的 **base 环境**,并一键把能自动修的补上:
  ① 配置文件      —— 建了吗(否则各命令用默认 provider=mock)
  ② LLM provider  —— 配了 API key 吗(否则 agent/写作只能走 mock 占位)
  ③ stats 组      —— pingouin/pandas/scipy(pystat MCP 真算、跑生成的统计脚本)
  ④ full 组       —— prompt_toolkit/rich(REPL 实时联想;方向键 readline 已兜底)

能自动装的(stats/full,pip)→ bootstrap(apply=True) 一键补;不能自动的(API key)→
列为「待你手动」并给确切命令。全程 fail-safe:装失败不阻断,如实报告。

纯逻辑用依赖注入(detect_fn/provider_fn/installer),离线可单测,不实际联网。
"""

from __future__ import annotations

# base 环境需要的可自动安装组(见 bootstrap.DEP_GROUPS)
BASE_GROUPS = ("stats", "full")


def _default_detect():
    from psyclaw.bootstrap import detect
    return detect()


def _default_config():
    from psyclaw import config as cfg
    return cfg.load_config()


def _default_provider(conf):
    from psyclaw.providers import get_provider
    return get_provider(conf)


def diagnose(project_dir: str = ".", *, detect_fn=None, config_fn=None,
             provider_fn=None) -> list[dict]:
    """返回 base 环境检查项列表。纯逻辑(依赖注入),不装任何东西。

    每项:{key, label, ok, detail, fix, auto, group?}
      auto=True 表示 bootstrap(apply) 能自动装(pip 组);False 表示须用户手动(如 API key)。
    """
    detect = detect_fn or _default_detect
    load_conf = config_fn or _default_config
    make_provider = provider_fn or _default_provider

    checks: list[dict] = []

    # ① 配置文件
    conf = load_conf()
    has_conf = conf.get("_source", "(defaults)") != "(defaults)"
    checks.append({
        "key": "config", "label": "配置文件", "ok": has_conf, "auto": False,
        "detail": conf.get("_source", "(defaults)") if has_conf else "未创建(用默认)",
        "fix": "" if has_conf else "psyclaw config  # 交互设置 provider/model",
    })

    # ② LLM provider key(mock 或空 key = 未配)
    try:
        prov = make_provider(conf)
        keyed = bool(getattr(prov, "api_key", "")) and prov.name != "mock"
        pname = prov.name
    except Exception:  # noqa: BLE001
        keyed, pname = False, "?"
    checks.append({
        "key": "provider", "label": "LLM provider", "ok": keyed, "auto": False,
        "detail": f"{pname}(已配 key)" if keyed else f"{pname}(无 key → 走 mock 占位)",
        "fix": "" if keyed else "psyclaw config  或设置对应 API key 环境变量(如 DEEPSEEK_API_KEY)",
    })

    # ③④ 可自动安装的能力组
    d = detect()
    groups = d.get("groups", {})
    labels = {"stats": "统计后端(stats)", "full": "REPL 增强(full)"}
    fixes = {"stats": "psyclaw setup --env --online  或 pip install 'psyclaw[stats]'",
             "full": "psyclaw setup --env --online  或 pip install 'psyclaw[full]'"}
    for g in BASE_GROUPS:
        info = groups.get(g, {"ready": False, "missing": []})
        miss = [p for p, _ in info.get("missing", [])]
        checks.append({
            "key": g, "label": labels.get(g, g), "ok": bool(info.get("ready")),
            "auto": True, "group": g,
            "detail": "就绪" if info.get("ready") else "缺: " + ", ".join(miss),
            "fix": "" if info.get("ready") else fixes.get(g, ""),
        })
    return checks


def plan_installs(checks: list[dict]) -> list[str]:
    """从诊断结果挑出「缺失且可自动装」的组名(去重保序)。"""
    seen, out = set(), []
    for c in checks:
        if c.get("auto") and not c["ok"] and c.get("group") and c["group"] not in seen:
            seen.add(c["group"])
            out.append(c["group"])
    return out


def _default_installer(groups: list[str]) -> dict:
    """对每个缺失组跑 pip 安装其缺失包。返回 {group: ok_bool}。"""
    from psyclaw.bootstrap import DEP_GROUPS, _pip_install, detect
    d = detect()["groups"]
    result = {}
    for g in groups:
        missing = [pip for pip, _ in d.get(g, {}).get("missing", [])]
        if not missing:
            result[g] = True
            continue
        result[g] = _pip_install(missing)
    return result


def bootstrap(project_dir: str = ".", *, apply: bool = False, installer=None,
              detect_fn=None, config_fn=None, provider_fn=None) -> dict:
    """诊断 base 环境;apply=True 则一键装可自动修的缺失组。

    返回 {checks, planned, installed, manual, all_ok}:
      planned  = 计划安装的组名;installed = {group: ok}(未 apply 时为空);
      manual   = 需用户手动处理的项(config/provider);all_ok = 全部就绪。
    """
    checks = diagnose(project_dir, detect_fn=detect_fn, config_fn=config_fn,
                      provider_fn=provider_fn)
    planned = plan_installs(checks)
    installed: dict = {}
    if apply and planned:
        inst = installer or _default_installer
        try:
            installed = inst(planned) or {}
        except Exception as exc:  # noqa: BLE001 — 装失败不阻断,如实记
            installed = {g: False for g in planned}
            installed["_error"] = str(exc)
        # 重新诊断以反映安装结果(注入的 fake detect 应体现变化;真安装同理)
        checks = diagnose(project_dir, detect_fn=detect_fn, config_fn=config_fn,
                          provider_fn=provider_fn)
    manual = [c for c in checks if not c["ok"] and not c.get("auto")]
    all_ok = all(c["ok"] for c in checks)
    return {"checks": checks, "planned": planned, "installed": installed,
            "manual": manual, "all_ok": all_ok}


def format_report(result: dict) -> str:
    """把 bootstrap 结果渲染成人读报告(纯文本 + 少量标记;CLI 上色另做)。"""
    lines = ["# 基础环境检查"]
    for c in result["checks"]:
        mark = "✓" if c["ok"] else "✗"
        lines.append(f"  {mark} {c['label']}: {c['detail']}")
        if not c["ok"] and c["fix"]:
            lines.append(f"      → {c['fix']}")
    if result["installed"]:
        ok = [g for g, v in result["installed"].items() if v is True]
        bad = [g for g, v in result["installed"].items() if v is False]
        if ok:
            lines.append("已自动安装: " + ", ".join(ok))
        if bad:
            lines.append("安装失败(请手动): " + ", ".join(bad))
    if result["manual"]:
        lines.append("待手动配置: " + ", ".join(c["label"] for c in result["manual"]))
    lines.append("环境状态: " + ("全部就绪 ✓" if result["all_ok"] else "有缺失,见上"))
    return "\n".join(lines)
