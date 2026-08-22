> **v0.23 legacy documentation.** 本页保留用于复现 PsyClaw v0.23.0；v0.24.0 的当前范围、接口与验收标准请以 开工纪要.md、架构蓝图.md 和 评测框架.md 为准。

# Skill Registry

PsyClaw 的 Skill 检索面向 Agent，而不是把一长串 `SKILL.md` 原文注入每轮上下文。

## 调用顺序

1. `skill_search`：按自然语言任务检索摘要，可加 `category`、`tags`、`scope` 和 `top_k`。
2. `skill_get`：确认名称后读取一个已启用 Skill 的完整正文。Registry 决定路径，工具不会接受任意文件路径；停用项仅返回元数据。
3. 按正文流程执行；Skill 本身是 Agent 指令，不是 PsyClaw Python 插件。

`skill_categories` 返回当前分类计数；`skill_registry_rebuild` 重建项目内 `.psyclaw/skill_registry.json`，不修改源 Skill。

## 分类

`research_design`、`literature`、`data_analysis`、`qualitative`、`writing`、`review`、`evidence`、`visualization`、`workflow`、`memory`、`general`。

Skill 的原始 `category` 会通过稳定别名归一化，例如 `method` → `research_design`、`meta` → `evidence`、`tooling` → `data_analysis`。Registry 同时记录标签、能力标题、输入输出声明、风险、scope、SHA-256 和 evidence level；没有明确证据级别时保持 `unverified`，不会把“已发现”冒充“已验证”。

## Agent 示例

```json
{"name":"skill_search","args":{"query":"做元分析并检查发表偏倚","category":"meta","top_k":5}}
```

没有命中时返回 `status: "no_match"`。Agent 应继续澄清或走普通流程，不编造 Skill 名称或能力。
