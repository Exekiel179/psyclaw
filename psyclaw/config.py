"""配置与交互式环境变量向导（stdlib only）。

层级（高→低）：环境变量 > ~/.psyclaw/.env > ~/.psyclaw/config.yaml > ./psyclaw.yaml
"""

from __future__ import annotations

import os
from pathlib import Path

HOME_DIR = Path.home() / ".psyclaw"
CONFIG_FILE = HOME_DIR / "config.yaml"
ENV_FILE = HOME_DIR / ".env"

DEFAULTS = {
    "provider": "mock",
    "model": "default",
    "base_url": "",
    "language": "zh",
    "figure_style": "apa7",
}


def load_env_file() -> None:
    """把 ~/.psyclaw/.env 的密钥载入进程环境(不覆盖已有环境变量)。"""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def _parse_simple(path: Path) -> dict:
    out: dict = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line and "=" not in line:
            continue
        sep = ":" if ":" in line else "="
        k, v = line.split(sep, 1)
        out[k.strip()] = v.strip()
    return out


def load_config() -> dict:
    load_env_file()
    conf = dict(DEFAULTS)
    source = "(defaults)"
    if CONFIG_FILE.exists():
        conf.update(_parse_simple(CONFIG_FILE))
        source = str(CONFIG_FILE)
    for key in list(conf) + ["provider", "model"]:
        env = os.environ.get(f"PSYCLAW_{key.upper()}")
        if env:
            conf[key] = env
            source += " + env"
    conf["_source"] = source
    return conf


def run_config_wizard(non_interactive: bool = False) -> int:
    from psyclaw import ui
    from psyclaw.providers import PRESETS

    HOME_DIR.mkdir(parents=True, exist_ok=True)
    print(ui.title("PsyClaw 配置向导"))
    print(ui.rule())

    if non_interactive:
        _write_config(dict(DEFAULTS), secrets={})
        print(f"已写入默认配置 → {CONFIG_FILE}")
        return 0

    conf = dict(DEFAULTS)
    secrets: dict = {}

    # -- provider 菜单 -------------------------------------------------------
    names = [n for n in PRESETS if n != "custom"] + ["custom"]
    print(ui.accent("选择 LLM Provider:"))
    for i, n in enumerate(names, 1):
        p = PRESETS[n]
        key_note = ui.dim("免 key") if p["key_env"] is None else ui.dim(p["key_env"])
        print(f"  {ui.paint(str(i), 'bryellow'):>4}. {n:<10} {p['label']:<28} {key_note}")
    sel = _ask("编号或名称", "1")
    if sel.isdigit() and 1 <= int(sel) <= len(names):
        provider = names[int(sel) - 1]
    elif sel.lower() in PRESETS:
        provider = sel.lower()
    else:
        provider = "mock"
    preset = PRESETS[provider]
    conf["provider"] = provider

    if preset.get("models"):
        print(ui.dim("  可选模型: " + " · ".join(preset["models"])))
    conf["model"] = _ask("  模型名", preset["model"] or "default")
    default_base = preset["base_url"]
    note = "(官方端点;中转站/自建填完整地址)" if default_base else "(必填完整地址)"
    conf["base_url"] = _ask(f"  Base URL {note}", default_base)

    if preset["key_env"]:
        key = _ask(f"  {preset['key_env']}(留空跳过,写入 .env 不入库)", "", secret=True)
        if key:
            secrets[preset["key_env"]] = key
    else:
        print(ui.dim("  本地模型,无需 API key ✓"))

    # -- MCP ----------------------------------------------------------------
    if _ask_yn("启用 Zotero MCP?", True):
        zk = _ask("  ZOTERO_API_KEY", "", secret=True)
        if zk:
            secrets["ZOTERO_API_KEY"] = zk
        zl = _ask("  ZOTERO_LIBRARY_ID", "")
        if zl:
            secrets["ZOTERO_LIBRARY_ID"] = zl

    if _ask_yn("启用 文献检索 MCP?", True):
        conf["lit_sources"] = _ask("  数据源 [pubmed,semantic-scholar,openalex,arxiv]",
                                    "openalex,semantic-scholar")

    conf["figure_style"] = _ask("图片风格 [apa7/nature/frontiers/minimal]",
                                DEFAULTS["figure_style"])

    if _ask_yn("配置消息通知(Telegram/企业微信)?", False):
        tk = _ask("  TELEGRAM_BOT_TOKEN(@BotFather 创建,留空跳过)", "", secret=True)
        if tk:
            secrets["TELEGRAM_BOT_TOKEN"] = tk
            secrets["TELEGRAM_CHAT_ID"] = _ask(
                "  TELEGRAM_CHAT_ID(白名单;不知道就先空着,/start 时 bot 会告诉你)", "")
        wh = _ask("  WECOM_WEBHOOK_URL(企业微信群机器人 webhook,留空跳过)", "", secret=True)
        if wh:
            secrets["WECOM_WEBHOOK_URL"] = wh

    _write_config(conf, secrets)
    print()
    print(ui.ok(f"✓ 配置已写入 {CONFIG_FILE}"))
    if secrets:
        print(ui.ok(f"✓ 密钥已写入 {ENV_FILE}") + ui.dim("(请勿提交该文件)"))
    print(ui.dim("运行 `psyclaw doctor` 自检。"))
    return 0


def _write_config(conf: dict, secrets: dict) -> None:
    HOME_DIR.mkdir(parents=True, exist_ok=True)
    lines = ["# PsyClaw config"]
    for k, v in conf.items():
        if not k.startswith("_"):
            lines.append(f"{k}: {v}")
    CONFIG_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if secrets:
        existing = {}
        if ENV_FILE.exists():
            for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    existing[k.strip()] = v.strip()
        existing.update({k: v for k, v in secrets.items() if v})
        env_lines = ["# PsyClaw secrets - DO NOT COMMIT"]
        env_lines += [f"{k}={v}" for k, v in existing.items()]
        ENV_FILE.write_text("\n".join(env_lines) + "\n", encoding="utf-8")


def _ask(prompt: str, default: str, secret: bool = False) -> str:
    suffix = f" [{default}]" if default and not secret else ""
    try:
        val = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        return default
    return val or default


def _ask_yn(prompt: str, default: bool) -> bool:
    d = "Y/n" if default else "y/N"
    try:
        val = input(f"{prompt} [{d}]: ").strip().lower()
    except EOFError:
        return default
    if not val:
        return default
    return val.startswith("y")
