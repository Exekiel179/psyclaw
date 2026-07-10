"""把 analysis workflow 的推荐分析接到 pystat MCP 后端(v0.10 feat-053)。

闭环最后一公里:recommend_analysis 已确定性地选出检验类型 + 角色列,pystat MCP 已能算。
本模块把二者连起来——rec_to_pystat_call 做纯映射,run_via_pystat 经 MCP 客户端真跑。

纪律:全程 fail-safe——pystat 不可用/pingouin 未装/任何异常 → 返回 None,调用方(step_analysis)
仍有生成的脚本兜底,绝不阻断流程。client_factory 可注入,离线可测。
"""

from __future__ import annotations


def rec_to_pystat_call(rec: dict, csv_path: str) -> tuple[str, dict] | None:
    """recommend_analysis 结果 → (pystat 工具名, args)。无法映射返回 None。纯函数。"""
    a = (rec or {}).get("analysis")
    if a == "ttest":
        return "pystat_ttest", {"csv_path": csv_path, "dv": rec["dv"],
                                "group": rec["group"]}
    if a == "anova":
        return "pystat_anova", {"csv_path": csv_path, "dv": rec["dv"],
                                "between": rec["group"]}
    if a == "regression":
        return "pystat_regression", {"csv_path": csv_path, "dv": rec["dv"],
                                     "predictors": ",".join(rec.get("iv", []))}
    if a == "correlation":
        return "pystat_correlation", {"csv_path": csv_path, "x": rec["x"],
                                      "y": rec["y"]}
    if a == "descriptives":
        return "pystat_describe", {"csv_path": csv_path}
    return None


def _default_pystat_client():
    """查目录里已启用+健康+有 command 的 pystat,返回一个 MCPClient;不可用返回 None。"""
    try:
        from psyclaw.mcp.client import MCPClient
        from psyclaw.mcp.manager import list_mcp_catalog_with_health
        for entry in list_mcp_catalog_with_health():
            if entry.get("name") == "pystat":
                if (entry.get("enabled") and entry.get("command")
                        and (entry.get("health") or {}).get("ok")):
                    return MCPClient(entry["command"])
                return None
    except Exception:  # noqa: BLE001
        return None
    return None


def _real_result(out: str | None) -> str | None:
    """把「统计库未装时返回的脚本骨架」判为无结果——脚本不是数值,回填稿件会造成
    『看着像跑过了』的假象(学术诚信:不假装算出结果)。"""
    if not out or "统计库未安装" in out:
        return None
    return out


def run_via_pystat(rec: dict, csv_path: str, client_factory=None) -> str | None:
    """经 pystat MCP 跑推荐分析,返回结果文本;不可用/失败/仅脚本骨架 → None(fail-safe)。"""
    call = rec_to_pystat_call(rec, csv_path)
    if not call:
        return None
    tool, args = call
    client = (client_factory or _default_pystat_client)()
    if client is None:
        return None
    try:
        with client:
            out = client.call_tool(tool, args)
        return _real_result(out)
    except Exception:  # noqa: BLE001 — MCP 任何异常都不阻断,退回脚本兜底
        return None


def run_meta_via_pystat(csv_path: str, client_factory=None) -> str | None:
    """经 pystat MCP 跑随机效应元分析(v0.12 feat-072);同样 fail-safe。"""
    client = (client_factory or _default_pystat_client)()
    if client is None:
        return None
    try:
        with client:
            out = client.call_tool("pystat_meta", {"csv_path": csv_path})
        return _real_result(out)
    except Exception:  # noqa: BLE001
        return None
