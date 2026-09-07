/**
 * In-session /help content: three sticky modes + the commands people actually use.
 * Detailed product docs remain in docs/; this is the terminal-facing whitepaper snippet.
 */

export function formatSessionHelp(): string {
  return [
    "# PsyClaw 使用速览",
    "",
    "## 三种模式（Shift+Tab 循环）",
    "",
    "| 模式 | 用途 |",
    "| --- | --- |",
    "| **chat** | 普通对话；不强制研究流水线 |",
    "| **analysis** | 澄清 → 分析方案 → 跑数 → 分析报告；统计意图会 soft-takeover 到 analysis-plan |",
    "| **academic** | ARS 文献/写作/审稿；消费 analysis/HANDOFF.md，不重选主检验 |",
    "",
    "Thinking 深度：`Ctrl+Shift+T`（终端里比 Ctrl+Shift+Tab 更可靠）。",
    "",
    "## 建议流程",
    "",
    "1. `/init` 搭建工作区（可稍后补；若直接下发统计/写作，会先提醒确认）。",
    "2. Shift+Tab 到 **analysis**，用自然语言描述数据与问题 → 模型路由到方案。",
    "3. 对每个拟做的分析做选择（首选项应是具体新方法；「已经足够」只是可选项）。",
    "4. 回复「可以 / 确认」即继续执行；也可 `/plan auto` 跳过人工审批（结果会标注未经人审）。",
    "5. 分析前/后在 Panel「核对清单」勾选；跳过会写入「未经核对」。",
    "6. Shift+Tab 到 **academic** 写论文 / 审稿。",
    "",
    "## 常用命令",
    "",
    "| 命令 | 说明 |",
    "| --- | --- |",
    "| `/init` | 初始化工作区（data/、analysis/、literature/、paper/、.psyclaw/） |",
    "| `/plan` | 分析方案状态；`auto` 无人审批模式；自然语言「可以」也可确认 |",
    "| `/crosscheck` | 交叉核验（引文 / 格式 / 要求 / 统计结果）；也可写 `/verify` |",
    "| `/grill` | 逐题压力测试（academic-grill；不是人物扮演） |",
    "| `/skill:huashu-nuwa` | 女娲：蒸馏任意人物/主题为 Skill（花叔 nuwa，随包） |",
    "| `/skill:kahneman-perspective` 等 | 随包人物镜头：卡尼曼 / Gelman / Freud（精神分析代表） |",
    "| `/review` | 多角色模拟同行评审 |",
    "| `/panel` | 打开科研工作台（核对清单 + 对话页） |",
    "| `/skill:<name>` | 显式调用技能；academic 下 ARS/Nature/compose 白名单可软路由 |",
    "| `/help` | 本说明 |",
    "",
    "完整白皮书见仓库 `docs/使用白皮书.md`（当前索引到版本化白皮书）。",
  ].join("\n");
}
