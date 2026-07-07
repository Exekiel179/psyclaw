"""多轮工具调用集成测试(v0.6 feat-046)——证明「多轮对话工具调用不出问题」。

用一个脚本化 provider 走一段贴近真实的多轮序列:正常调用 → 畸形 args 自纠 →
截断续写 → 混合并行调用 → 最终答案;全程断言:工具不崩、失败如实上报、
provider 只收到合法消息序列、循环正常收敛。
"""
from __future__ import annotations

from psyclaw import toolloop as TL


class ScriptedProvider:
    """按脚本逐轮回复;可选携带 last_stop_reason;记录每次收到的消息用于不变量断言。"""
    name = "scripted"

    def __init__(self, steps):
        # steps: [(reply, stop_reason), ...]
        self._steps = list(steps)
        self.last_stop_reason = ""
        self.seen: list = []
        self.chats = 0

    def chat(self, messages, system=""):
        self.chats += 1
        self.seen.append([dict(m) for m in messages])
        reply, reason = self._steps.pop(0) if self._steps else ("最终答案", "end_turn")
        self.last_stop_reason = reason
        return iter([reply])


def _tools():
    log = []

    def echo(a):
        # 严格要求 dict 且有 x;拿到畸形参数会 KeyError/AttributeError——用来验证护栏
        log.append(a)
        return f"echoed {a['x']}"

    return {"echo": {"desc": "回声", "args": "x:int",
                     "run": echo, "side_effect": False}}, log


def test_realistic_multiturn_sequence_never_breaks():
    steps = [
        # 1) 正常调用
        ('先看看\n```tool\n{"name":"echo","args":{"x":1}}\n```', "end_turn"),
        # 2) 畸形 args(双重编码 JSON 字符串)——应被规范化后成功,不崩
        ('```tool\n{"name":"echo","args":"{\\"x\\":2}"}\n```', "end_turn"),
        # 3) 畸形 args(list)——parse 拦截为失败,回灌引导;工具不被调用崩溃
        ('```tool\n{"name":"echo","args":[9,9]}\n```', "end_turn"),
        # 4) 未知工具——如实报未知,模型可自纠
        ('```tool\n{"name":"nope","args":{}}\n```', "end_turn"),
        # 5) 被 max_tokens 截断的半个 tool 块——续写而非当答案
        ('```tool\n{"name":"echo","args":{"x":', "max_tokens"),
        # 6) 重发完整
        ('```tool\n{"name":"echo","args":{"x":3}}\n```', "end_turn"),
        # 7) 最终答案
        ("多轮完成,最终答案。", "end_turn"),
    ]
    prov = ScriptedProvider(steps)
    tools, log = _tools()
    res = TL.run_tool_loop(prov, "sys", [{"role": "user", "content": "任务"}],
                           tools=tools, max_iters=20)

    # 正常收敛到答案
    assert res["stopped"] == "answered"
    assert res["final"] == "多轮完成,最终答案。"

    # 工具只在参数合法时真正执行(x=1,2,3),畸形/未知的没崩进 run
    assert log == [{"x": 1}, {"x": 2}, {"x": 3}]

    # 畸形 args 与未知工具都被如实标为失败(ok=False),而非误标成功或抛穿
    outputs = {t["name"]: t for t in res["trace"]}
    fails = [t for t in res["trace"] if not t["ok"]]
    assert any("对象" in t["output"] for t in fails)      # list-args 引导
    assert any("未知工具" in t["output"] for t in fails)  # 未知工具

    # 全程 provider 只收到合法消息序列(非空 content + 角色交替 + 首条 user)
    for msgs in prov.seen:
        assert msgs and msgs[0]["role"] == "user"
        assert all(str(m["content"]).strip() for m in msgs)
        roles = [m["role"] for m in msgs]
        assert all(roles[i] != roles[i + 1] for i in range(len(roles) - 1))


def test_multiturn_survives_all_failing_tools_then_answers():
    """连续工具失败(但参数各不同)不误判无进展,模型最终仍能给答案。"""
    steps = [
        ('```tool\n{"name":"echo","args":[1]}\n```', "end_turn"),   # 失败1
        ('```tool\n{"name":"echo","args":[2]}\n```', "end_turn"),   # 失败2(不同 args)
        ("没拿到数据,但据现有信息给出结论。", "end_turn"),
    ]
    prov = ScriptedProvider(steps)
    tools, _ = _tools()
    res = TL.run_tool_loop(prov, "s", [{"role": "user", "content": "q"}],
                           tools=tools, max_iters=20)
    assert res["stopped"] == "answered"
    assert all(not t["ok"] for t in res["trace"])
