/**
 * In-session /help: open the Panel「使用速览」page. Terminal gets a short tip only.
 * Structured document powers the Panel view.
 */

export type SessionHelpDocument = {
  title: string;
  modes: Array<{ id: string; label: string; blurb: string }>;
  thinking: string;
  steps: string[];
  commands: Array<{ cmd: string; blurb: string }>;
  notes: string[];
};

export function sessionHelpDocument(): SessionHelpDocument {
  return {
    title: "PsyClaw 使用速览",
    modes: [
      { id: "chat", label: "chat", blurb: "普通对话；不强制研究流水线" },
      { id: "analysis", label: "analysis", blurb: "澄清 → 方案 → 跑数 → 分析报告；统计意图会 soft-takeover" },
      { id: "academic", label: "academic", blurb: "ARS 文献/写作/审稿；消费 analysis/HANDOFF.md，不重选主检验" },
    ],
    thinking: "Thinking 深度：Ctrl+Shift+T（比 Ctrl+Shift+Tab 更可靠）",
    steps: [
      "/init 搭建工作区（可稍后；直接统计/写作时会先提醒）。",
      "Shift+Tab 到 analysis，用自然语言描述数据与问题。",
      "对每个拟做的分析做选择（优先具体新方法；「已经足够」仅为可选项）。",
      "回复「可以 / 确认」继续；或 /plan auto 跳过人工审批（标注未经人审）。",
      "分析前/后在「核对清单」勾选；跳过会写入「未经核对」。",
      "Shift+Tab 到 academic 写论文 / 审稿。",
    ],
    commands: [
      { cmd: "/init", blurb: "初始化工作区" },
      { cmd: "/plan", blurb: "分析方案；auto 无人审批；自然语言「可以」也可确认" },
      { cmd: "/crosscheck", blurb: "交叉核验（也可 /verify）" },
      { cmd: "/grill", blurb: "学术压力测试（academic-grill）" },
      { cmd: "/review", blurb: "多角色模拟同行评审" },
      { cmd: "/panel", blurb: "科研工作台" },
      { cmd: "/skill:<name>", blurb: "显式调用技能；学者/期刊蒸馏用推荐 distill-scholar / distill-journal" },
      { cmd: "/help", blurb: "打开本页" },
    ],
    notes: [
      "随包含若干方法学人物镜头；学者/期刊风格蒸馏见推荐安装 `distill-scholar` / `distill-journal`（https://github.com/Exekiel179/distill-skills）。",
      "完整白皮书见仓库 docs/使用白皮书.md。",
    ],
  };
}

/** Short terminal tip when Panel help is opened (or as fallback). */
export function formatSessionHelpBrief(url?: string): string {
  if (url) return `使用速览已在 Panel 打开：\n${url}`;
  return "使用速览请打开 Panel（/help 会自动跳转，或执行 /panel help）。";
}

/** Plain markdown fallback when Panel cannot start. */
export function formatSessionHelp(): string {
  const doc = sessionHelpDocument();
  return [
    `# ${doc.title}`,
    "",
    "## 三种模式（Shift+Tab）",
    ...doc.modes.map((mode) => `- **${mode.label}**：${mode.blurb}`),
    "",
    doc.thinking,
    "",
    "## 建议流程",
    ...doc.steps.map((step, index) => `${index + 1}. ${step}`),
    "",
    "## 常用命令",
    ...doc.commands.map((row) => `- \`${row.cmd}\` — ${row.blurb}`),
    "",
    ...doc.notes.map((note) => `- ${note}`),
  ].join("\n");
}
