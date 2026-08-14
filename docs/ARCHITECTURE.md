# PsyClaw 架构 — 按研究类型路由的可组合工作流系统

PsyClaw 是**研究编排 harness**:按研究类型把流程路由起来,统计计算交给外部库/MCP。
核心是一个**四层 + 两横切**的可组合结构。

```
L0  路由 Router        两种公开入口:`chat` / `run <类型>`（`run` 不带类型=自动继续）
        │              （旧 agent/loop/*-loop 是兼容入口,不再暴露为心智模型）
L1  流程 Workflow       每类研究 = 一份声明式「步骤 + 前置检查」定义;引擎按定义跑(HITL + 总验收)
        │              （完整跑 = 高级 loop;psyclaw/workflows/engine.py）
L2  子功能 Step         每步都能①单独直接用(多数本就是 CLI 命令)②拆出来 ③拼进任意 workflow
        │              （psyclaw/workflows/steps.py）
L3  实现 Skill + MCP    每个 Step 是薄壳,真正干活委托既有命令 / skill / MCP(统计走这层)
─────────────────────────────────────────────────────────────
横切 A  Harness         每个 Step 带 gate(前置约束,fail-closed);总验收机器可读
横切 B  Memory          三层记忆贯穿路由与各步(方法学偏好/期刊/惯例)
```

## L0 路由：chat / run

| 入口 | 作用 | 底层引擎 |
|---|---|---|
| `chat`(缺省 `psyclaw`) | 一起做：边聊边推进 | REPL + agent_runtime + toolloop |
| `run <类型>` | 交给它做：按步骤执行一条流程 | workflow |
| `run`（不带类型） | 交给它做：根据状态继续下一步 | autoloop + workflow |

`psyclaw/modes.py` 是共享路由真源:`run analysis/meta/literature/qualitative` 进入声明式
workflow。固定 pipeline 和通用 planner→critic 回路只保留旧命令兼容,不再作为公开 `run` 类型。

### chat 的规划/执行分离

交互式 `chat` 与一次性 `psyclaw agent` 共用 `psyclaw/agent_runtime.py`：

```text
Planner（只产 DAG）
  → Scheduler（关键路径留在当前线程）
    → Executor（主线）
    → Executor forks（同质、独立 provider 实例、有界并发）
  → Verifier（工具回执 + 必需产物 + 完成契约）
  → Finisher（只汇总已验收结果，不得再调用工具）
```

- Planner 只输出 JSON 任务图，不能执行工具或声称任务已完成。
- Scheduler 默认使用 `agent_workers: 3`，硬上限为 4。只有声明了项目内 `owned_paths`、
  标记为 `parallel_safe` 且真实写入范围不重叠的就绪任务才会 fork；Windows 路径按大小写
  无关规则比较，软链接/联接路径拒绝写入，冲突任务自动串行。
- 每个 Executor 使用同一 `executor` 角色配置和工具能力，但持有独立 Provider 实例与任务上下文。
  fork 任务只能执行只读工具或写入自己拥有的路径，不能执行网络发布等非文件副作用；自动读文件
  和列目录也只能访问项目根内、非凭据目录、非链接的路径。
- Verifier 不采信“已经完成”等自然语言，而是检查结构化工具回执、成功调用数和必需产物；
  必需任务未通过时 Finisher 不运行。失败任务最多自动纠偏重试一次，但只要已尝试副作用，
  无论回执成功与否都停止自动重放，避免“提交成功但响应超时”造成重复外部写入。
- 工具循环会识别“我现在执行/等待结果”等未伴随工具调用的承诺，自动要求模型真正调用工具；
  连续空转则停止。纠偏状态会保留到副作用真正出现，该批全部副作用都强制人工确认。
- `max_iters` 是所有 Executor、副本和重试共享的全局模型调用预算，不能被任务拆分放大；角色 Provider
  与会话 Provider 属于不同端点时，数据发送前只确认一次，并对任务上下文和结果摘要统一脱敏。
- REPL 持续显示 `plan/fork/main/verify/join` 进度，运行记录写入
  `.psyclaw/agent_runs.jsonl`，包含计划任务、验收状态、尝试次数与执行线程。

## L1 流程：声明式 workflow 定义

一个 workflow 是**纯数据**(`psyclaw/workflows/registry.py`):

```python
LIT_REVIEW = {
    "id": "lit-review", "name": "文献综述", "command": "review-lit",
    "steps": [
        Step("clarify",    "研究准备检查",        run=..., gate=gate_clarify_complete),
        Step("lit_search", "文献检索(PRISMA 识别)", run=step_lit_search),
        Step("screen",     "筛选(PRISMA)",        run=step_screen),
        Step("synthesize", "合成结构化综述",       run=step_synthesize),
        Step("review",     "同行评审",            run=step_review, optional=True),
    ],
}
```

引擎(`run_workflow`)对每个 Step:① 跑 `gate`(harness 约束,不过则 fail-closed,除非 optional)
② 跑 `run` ③ 记 artifact/evidence 和恢复检查点 ④ `--confirm-each` 时步间征求人工确认。
公开默认连续执行;`--resume` 只在目标、输入和已完成产物一致时恢复。
末尾产机器可读总验收 `notes/workflow_summary.json`(`workflow_verdict` 纯函数,可单测)。

## L2 子功能：可单用 / 可拆 / 可拼

每个 Step 的 `run` 都是薄壳,复用既有能力:
- `prepare`(`clarify` 兼容别名)→ `psych.clarify.check_card`(前置检查)
- `lit_search` → `psych.litsearch.search`(= `psyclaw lit` 的检索核)
- `screen` → `workflows.steps.screen_papers`(**新子功能**,独立纯函数,可 `import` 直接调用)
- `synthesize` → `psych.synthesize.synthesize_review`
- `review` → `review.run_review`

所以:`psyclaw lit`/`prepare`/`review` 仍可单独用;它们也是 workflow 的步骤;
高级用户编辑 registry 即可自由拼装新流程。

## L3 实现：Skill + MCP（统计在这层）

Step 之下是真正的实现层:
- **既有命令/模块**(lit/synthesize/review/export…)
- **Skills**(academic-paper / deep-research / ARS 等 `.claude/skills`)——"怎么做好"的指令+agent
- **MCP**(`psyclaw mcp --serve {mne,spss,mplus,stata}`、zotero…)——外部专业工具

统计(描述/回归/因子/生存/元分析…)**已整体外移到这层**,不在 PsyClaw 本体(见 `CLAUDE.md`)。
实证/元分析流程的"分析"步会委托到 MCP 统计后端或外部库。

**v0.5:agent 直连 MCP。** `psyclaw/mcp/client.py`(stdio JSON-RPC 客户端)+ `agent_tools.py`
把已启用+健康的 MCP 服务器工具惰性并入 agent 工具集(`mcp__<server>__<tool>`,fail-closed 批准)。
至此 L3 的 MCP 不再只是"另起进程手动跑",agent 循环可在多步推理中直接调用——编排纵深落地。

**v0.8:pystat 后端闭环。** `psyclaw/mcp/servers/pystat_server.py` 委托 pingouin/pandas 做
常规统计(t 检验/相关/方差/回归/描述),库在则真跑(带效应量+CI)、不在则给可运行脚本。
它随 registry 的 `command` 被 feat-040 自动浮出为 `mcp__pystat__*`——agent 可在推理中直接
委托统计,不必让用户手动跑脚本。至此「统计外移到成熟库/MCP」从口号变成 agent 触手可及的工具。

**v0.10:workflow 也接上,端到端闭环。** `workflows/pystat_bridge.py` 把 `recommend_analysis`
的检验类型+角色列纯映射到 pystat 工具,`step_analysis` 生成脚本后 best-effort 经 pystat MCP
直接跑,结果落 `outputs/analysis_result.txt`(fail-safe:不可用仍有脚本)。至此「数据→画像→
推荐→出结果」在 workflow 层也贯通——agent 路径(v0.5)与 workflow 路径都能落到同一 pystat 后端。

## 两条横切

- **Harness**:每个 Step 的 `gate` = 前置约束(如澄清未完成不开工、确证须先预注册);
  总验收 fail-closed;`feature_list.json` 为机器可读 state 真源。对标 learn-harness-engineering。
- **Memory**:三层记忆(画像/惯性/教训卡)贯穿——路由默认值、各步行为受方法学偏好影响。

## 怎么加一条新流程

1. 在 `steps.py` 写缺的 Step(薄壳,委托既有命令/skill/MCP)+ 需要的 gate。
2. 在 `registry.py` 加一个 workflow dict(`id`/`name`/`command`/`steps`)。
3. 在 `modes.py` 把新的 run 类型映射到 workflow;普通用户不再新增顶层模式命令。
4. 加 `tests/test_workflows.py` 用例(引擎用 mock 步骤、子功能纯函数单测)。

## 现状

- ✅ 公开入口收敛为 `chat / run`;`run` 下含 literature/meta/analysis/qualitative，省略类型时进入自动继续
  四条具备稳定输入、步骤、产物和验收契约的 workflow。
- "统计外移"两处样板:`meta` 生成委托 statsmodels 的脚本(随机效应 DL + I²/τ²/Q + Egger);
  `analysis` 据数据画像**推荐分析**(t/ANOVA/相关/回归/描述)并生成委托 pingouin/scipy 的脚本——
  仓内**不算任何统计**。`qualitative` 是解释性分析:L3 = LLM 辅助编码/主题分析(研究者复核 HITL)。
- 子功能(独立纯函数,可单用):`screen_papers`、`validate_effects`/`generate_meta_script`、
  `profile_data`/`recommend_analysis`/`generate_analysis_script`、`load_transcripts`。
- `tests/test_workflows.py` 35 例;meta 与 analysis 生成脚本均经 C:\Python314 实跑 exit 0。
- 下一步:各分析步从"生成脚本"升级为"可选直连 MCP 统计后端";质性编码升级为专用 skill。

## 资料编译与 Skill 晋升

`psyclaw.materials` 负责单文件/视频资料转换与 SHA-256 审计；
`psyclaw.knowledge_compile` 将资料目录编译为 `materials/`、`INDEX.md`、`manifest.json`、
`claims.json`、`validation.json` 和 staged/v0 `SKILL.md`。编译只证明材料可导航，不证明规则成立。

Skill 晋升采用 fail-closed：必须存在带来源的 `verified` claim，并且 `known`、`forward`、
`contrast`、`boundary` 四类验证全部通过，才能写入 `status: promoted` 和 `evidence_level: v3`。
`psyclaw.handoff` 把目标、完成项、下一步和阻塞同时写入 Markdown 与 JSON，供下一会话先核验再继续。

`psyclaw.figures.compose_figures` 只负责已有科研图的确定性多面板排版和哈希审计；统计图的数值、
坐标轴和误差线仍由 matplotlib/R/SmartPlot 等成熟工具生成，并继续接受 `FIG.honest` 质量检查。

### Agent-first 工具面

上述能力的主入口不是 CLI，而是 `psyclaw.academic_tools.merge_academic_tools()` 注册到
`toolloop.build_tools()` 的原生工具。工具使用明确参数契约和结构化 JSON 返回；所有写盘操作标记为
`side_effect=True`，由 Agent loop 的审批层 fail-closed。路径解析限制在项目根目录内，并额外禁止
`data/raw`、`.git` 和 `.psyclaw`。同名 CLI 仅供人类调试，已从 CLI 自动工具化列表排除，避免 Agent
同时看到两套接口。
# Unified architecture

The canonical architecture and migration ownership map now lives in
[`UNIFIED_ARCHITECTURE.md`](UNIFIED_ARCHITECTURE.md). This document retains
module-level implementation details; new execution, artifact, policy, and
evidence decisions must follow the unified contract first.
