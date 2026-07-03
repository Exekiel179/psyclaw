"""PsyClaw 插件系统(stdlib only)—— 用户放一个 .py 文件即可扩展 REPL/agent。

插件 = 放在 ``<项目>/.psyclaw/plugins/`` 或 ``~/.psyclaw/plugins/`` 下的 Python 文件,
暴露 ``register(api)``。api 提供三个扩展点:

    def register(api):
        api.add_tool("my_tool", "描述", "x:str", lambda a: f"echo {a.get('x')}")
        api.add_command("/hello", "打招呼", lambda arg: print(f"你好 {arg}"))
        api.add_system("# 额外领域知识\\n…")

- **add_tool**:进 agent 工具循环(toolloop);side_effect=True 的工具照常走批准门。
- **add_command**:进 REPL slash 命令(补全联想同步出现)。
- **add_system**:追加进每轮 system 提示。

纪律:每个插件独立 try/except 加载(一个坏插件不拖垮 REPL,错误进 registry.errors 可见);
插件名不得覆盖内置工具/命令(内置优先,冲突记 errors);只加载**用户自己放进目录**的文件
(和任何插件系统一样,插件即代码——别装来路不明的)。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


SCOPE_LABEL = {"project": "用户·项目", "global": "用户·全局", "builtin": "内置"}


class PluginApi:
    """传给插件 register(api) 的注册接口。"""

    def __init__(self, name: str, scope: str, registry: "PluginRegistry") -> None:
        self._name = name
        self._scope = scope
        self._reg = registry

    def _tag(self) -> str:
        return f"[插件:{self._name}·{SCOPE_LABEL.get(self._scope, self._scope)}]"

    def add_tool(self, name: str, desc: str, args: str, run,
                 side_effect: bool = False) -> None:
        self._reg.tools.setdefault(name, {
            "desc": f"{desc} {self._tag()}", "args": args,
            "run": run, "side_effect": bool(side_effect)})

    def add_command(self, slash: str, desc: str, handler) -> None:
        slash = slash if slash.startswith("/") else "/" + slash
        self._reg.commands.setdefault(slash, {
            "desc": f"{desc} {self._tag()}", "handler": handler})

    def add_system(self, text: str) -> None:
        if text and text.strip():
            self._reg.systems.append(text.strip())


class PluginRegistry:
    def __init__(self) -> None:
        self.tools: dict[str, dict] = {}
        self.commands: dict[str, dict] = {}
        self.systems: list[str] = []
        self.loaded: list[dict] = []      # [{name, scope}]
        self.errors: list[str] = []


def plugin_dirs(project_dir: str = ".") -> list[tuple[Path, str]]:
    """插件目录(存在才返回):[(路径, scope)];项目级(project)优先,再全局(global)。"""
    cands = [(Path(project_dir) / ".psyclaw" / "plugins", "project"),
             (Path.home() / ".psyclaw" / "plugins", "global")]
    out, seen = [], set()
    for d, scope in cands:
        key = str(d.resolve()) if d.exists() else str(d)
        if key not in seen and d.is_dir():
            seen.add(key)
            out.append((d, scope))
    return out


def load_plugins(project_dir: str = ".") -> PluginRegistry:
    """加载全部插件。每个插件独立 fail-safe;返回 registry(含 loaded[{name,scope}]/errors)。"""
    reg = PluginRegistry()
    for d, scope in plugin_dirs(project_dir):
        for f in sorted(d.glob("*.py")):
            if f.name.startswith("_"):
                continue
            name = f.stem
            try:
                spec = importlib.util.spec_from_file_location(
                    f"psyclaw_plugin_{name}", f)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)          # type: ignore[union-attr]
                register = getattr(mod, "register", None)
                if not callable(register):
                    reg.errors.append(f"{name}: 缺 register(api) 函数")
                    continue
                register(PluginApi(name, scope, reg))
                reg.loaded.append({"name": name, "scope": scope})
            except Exception as exc:  # noqa: BLE001  # 坏插件不拖垮宿主
                reg.errors.append(f"{name}: {exc}")
    return reg


def merge_plugin_tools(tools: dict, reg: PluginRegistry) -> dict:
    """把插件工具并进 agent 工具集(内置优先,同名冲突记 errors)。"""
    for name, t in reg.tools.items():
        if name in tools:
            reg.errors.append(f"插件工具 {name} 与内置同名,已忽略")
            continue
        tools[name] = t
    return tools
