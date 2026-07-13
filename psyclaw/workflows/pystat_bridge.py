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


def _skeleton_mark() -> str:
    """脚本骨架哨兵串,单一来源于产生它的 pystat_server(feat-079,防措辞漂移击穿守卫)。"""
    try:
        from psyclaw.mcp.servers.pystat_server import SKELETON_MARK
        return SKELETON_MARK
    except Exception:  # noqa: BLE001 — 极端导入失败也不放松守卫,退回历史措辞
        return "统计库未安装"


def _has_nonfinite(obj) -> bool:
    """递归查 JSON 载荷里的 NaN/inf——不可发表的数值绝不当真结果。"""
    import math
    if isinstance(obj, float):
        return not math.isfinite(obj)
    if isinstance(obj, dict):
        return any(_has_nonfinite(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_nonfinite(v) for v in obj)
    return False


def _real_result(out: str | None, ok: bool = True) -> str | None:
    """真结果守卫(feat-079 收紧为结构化判定):以下一律判为无结果 → None——

    ① 传输/工具层失败(call_tool_status 的 ok=False:启动失败/超时/isError/空);
    ② 脚本骨架(统计库未装,SKELETON_MARK 哨兵);
    ③ 工具返回的结构化错误载荷({"error": …},如列不匹配/校验失败);
    ④ 载荷含 NaN/inf 的退化数值。
    否则原样返回。学术诚信:错误串/骨架/坏数值回填稿件都会造成
    『看着像跑过了』的假象,fail-closed 宁缺毋滥。
    """
    if not ok or not out or _skeleton_mark() in out:
        return None
    import json
    head = out.split("\n\n", 1)[0].strip()
    if head.startswith("{"):
        try:
            payload = json.loads(head)
        except ValueError:
            return out          # 非 JSON 文本结果(如描述统计表)照常放行
        if isinstance(payload, dict) and "error" in payload:
            return None
        if _has_nonfinite(payload):
            return None
    return out


def _call_tool_status(client, tool: str, args: dict) -> dict:
    """统一走结构化调用;注入的旧式假客户端(仅有 call_tool)按 ok=True 兼容。"""
    if hasattr(client, "call_tool_status"):
        return client.call_tool_status(tool, args)
    return {"ok": True, "text": client.call_tool(tool, args)}


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
            res = _call_tool_status(client, tool, args)
        return _real_result(res["text"], ok=res["ok"])
    except Exception:  # noqa: BLE001 — MCP 任何异常都不阻断,退回脚本兜底
        return None


def run_meta_via_pystat(csv_path: str, client_factory=None) -> str | None:
    """经 pystat MCP 跑随机效应元分析(v0.12 feat-072);同样 fail-safe。"""
    client = (client_factory or _default_pystat_client)()
    if client is None:
        return None
    try:
        with client:
            res = _call_tool_status(client, "pystat_meta", {"csv_path": csv_path})
        return _real_result(res["text"], ok=res["ok"])
    except Exception:  # noqa: BLE001
        return None
