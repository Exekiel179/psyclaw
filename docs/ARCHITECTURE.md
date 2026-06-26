# PsyClaw 架构 — 按研究类型路由的可组合工作流系统

PsyClaw 是**研究编排 harness**:按研究类型把流程路由起来,统计计算交给外部库/MCP。
核心是一个**四层 + 两横切**的可组合结构。

```
L0  路由 Router        每类研究一条顶层命令:review-lit / empirical / meta / qualitative …
        │              （上层分类少而清晰,用户一眼知道用哪条）
L1  流程 Workflow       每类研究 = 一份声明式「步骤 + 门禁」定义;引擎按定义跑(HITL + 总验收)
        │              （完整跑 = 高级 loop;psyclaw/workflows/engine.py）
L2  子功能 Step         每步都能①单独直接用(多数本就是 CLI 命令)②拆出来 ③拼进任意 workflow
        │              （psyclaw/workflows/steps.py）
L3  实现 Skill + MCP    每个 Step 是薄壳,真正干活委托既有命令 / skill / MCP(统计走这层)
─────────────────────────────────────────────────────────────
横切 A  Harness         每个 Step 带 gate(前置约束,fail-closed);总验收机器可读
横切 B  Memory          三层记忆贯穿路由与各步(方法学偏好/期刊/惯例)
```

## L0 路由：每类研究一条顶层命令

| 命令 | 研究类型 | 状态 |
|---|---|---|
| `review-lit <主题>` | 文献综述 / 系统综述 | ✅ 已实现 |
| `empirical <主题>` | 实证研究(含实验设计;分析交外部统计/MCP) | 规划中 |
| `meta <effects.csv>` | 元分析 | 规划中 |
| `qualitative <主题>` | 质性研究 | 规划中 |

`research <主题>` 是不分类型的通用编排(沿用旧 pipeline);`--freeform` 走通用 HITL 回路。

## L1 流程：声明式 workflow 定义

一个 workflow 是**纯数据**(`psyclaw/workflows/registry.py`):

```python
LIT_REVIEW = {
    "id": "lit-review", "name": "文献综述", "command": "review-lit",
    "steps": [
        Step("clarify",    "澄清门禁",            run=..., gate=gate_clarify_complete),
        Step("lit_search", "文献检索(PRISMA 识别)", run=step_lit_search),
        Step("screen",     "筛选(PRISMA)",        run=step_screen),
        Step("synthesize", "合成结构化综述",       run=step_synthesize),
        Step("review",     "同行评审",            run=step_review, optional=True),
    ],
}
```

引擎(`run_workflow`)对每个 Step:① 跑 `gate`(harness 约束,不过则 fail-closed,除非 optional)
② 跑 `run` ③ 记 artifact/evidence ④ 非 auto 模式步间征求人工确认。
末尾产机器可读总验收 `notes/workflow_summary.json`(`workflow_verdict` 纯函数,可单测)。

## L2 子功能：可单用 / 可拆 / 可拼

每个 Step 的 `run` 都是薄壳,复用既有能力:
- `clarify` → `psych.clarify.check_card`(门禁)
- `lit_search` → `psych.litsearch.search`(= `psyclaw lit` 的检索核)
- `screen` → `workflows.steps.screen_papers`(**新子功能**,独立纯函数,可 `import` 直接调用)
- `synthesize` → `psych.synthesize.synthesize_review`
- `review` → `review.run_review`

所以:`psyclaw lit`/`clarify`/`review` 仍可单独用;它们也是 workflow 的步骤;
高级用户编辑 registry 即可自由拼装新流程。

## L3 实现：Skill + MCP（统计在这层）

Step 之下是真正的实现层:
- **既有命令/模块**(lit/synthesize/review/export…)
- **Skills**(academic-paper / deep-research / ARS 等 `.claude/skills`)——"怎么做好"的指令+agent
- **MCP**(`psyclaw mcp --serve {mne,spss,mplus,stata}`、zotero…)——外部专业工具

统计(描述/回归/因子/生存/元分析…)**已整体外移到这层**,不在 PsyClaw 本体(见 `CLAUDE.md`)。
实证/元分析流程的"分析"步会委托到 MCP 统计后端或外部库。

## 两条横切

- **Harness**:每个 Step 的 `gate` = 前置约束(如澄清未完成不开工、确证须先预注册);
  总验收 fail-closed;`feature_list.json` 为机器可读 state 真源。对标 learn-harness-engineering。
- **Memory**:三层记忆(画像/惯性/教训卡)贯穿——路由默认值、各步行为受方法学偏好影响。

## 怎么加一条新流程

1. 在 `steps.py` 写缺的 Step(薄壳,委托既有命令/skill/MCP)+ 需要的 gate。
2. 在 `registry.py` 加一个 workflow dict(`id`/`name`/`command`/`steps`)。
3. 在 `cli.py` 加顶层命令(`cmd_<x>` → `run_workflow(get_workflow("<id>"), topic)`)+ 注册 + 进 CORE_COMMANDS/分类。
4. 加 `tests/test_workflows.py` 用例(引擎用 mock 步骤、子功能纯函数单测)。

## 现状

- ✅ 引擎 + 注册表 + 文献综述流程(`review-lit`)+ PRISMA 筛选子功能;`tests/test_workflows.py` 12 例。
- 下一步:逐条灌 empirical / meta / qualitative,补对应子功能(生成式实验设计、效应量提取、质性编码),分析步对接 MCP。
