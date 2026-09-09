/**
 * In-session /help: open the Panel「使用速览」page. Terminal gets a short tip only.
 * Slash surface is Codex-style: bare command, or command + trailing free text.
 */

export type SessionHelpDocument = {
  title: string;
  subtitle: string;
  modes: Array<{ id: string; label: string; blurb: string; hint: string }>;
  thinking: string;
  steps: string[];
  commands: Array<{ cmd: string; blurb: string; group?: string }>;
  notes: string[];
};

export function sessionHelpDocument(): SessionHelpDocument {
  return {
    title: "使用速览",
    subtitle: "三种模式 · AI 核查 · 强制人审",
    modes: [
      {
        id: "chat",
        label: "对话",
        hint: "chat",
        blurb: "普通问答与研究协作；可用自然语言直接要分析、写作或资料整理。",
      },
      {
        id: "analysis",
        label: "分析",
        hint: "analysis",
        blurb: "澄清 → 方案 → 可复现脚本 → AI /crosscheck → 人审核实 → 分析报告。",
      },
      {
        id: "academic",
        label: "学术",
        hint: "academic",
        blurb: "文献、写作与评审；定稿前须 AI /crosscheck 且人审通过。",
      },
    ],
    thinking: "思考深度：Ctrl+Shift+T（多数终端比 Ctrl+Shift+Tab 更可靠）",
    steps: [
      "可选：/init 或 /init <研究目标> 搭建工作区。",
      "Shift+Tab 在 对话 → 分析 → 学术 间切换。",
      "分析模式：/plan 后逐项确认每个子分析；整体批准须完整输入「我已审阅并批准本方案」。",
      "大段 `/crosscheck` / `/verify` 须人先同意再开；收尾人审仍由 Panel「核实」/唤醒选项。",
      "人审通过后 /handoff 写入交接；切到学术模式继续文献、初稿或 /review。",
    ],
    commands: [
      { group: "研究", cmd: "/init [目标]", blurb: "初始化项目；尾随文本为研究目标" },
      { group: "研究", cmd: "/plan [目标]", blurb: "查看或新建分析方案；子项确认 + 仪式批准句" },
      { group: "研究", cmd: "/handoff", blurb: "人审通过后写入 analysis/HANDOFF.md" },
      { group: "研究", cmd: "/crosscheck [焦点]", blurb: "过程性 AI 核对：数据/引文真实性/格式" },
      { group: "研究", cmd: "/verify [焦点]", blurb: "整体性 AI 验证：结果成立性、引文与方法合理性" },
      { group: "研究", cmd: "/brainstorm [主题]", blurb: "研究方向头脑风暴" },
      { group: "研究", cmd: "/grill [主题]", blurb: "逐题学术压力测试" },
      { group: "研究", cmd: "/review [说明]", blurb: "多角色模拟同行评审" },
      { group: "研究", cmd: "/loop [目标|stop]", blurb: "有界推进；附带 stop 请求停止" },
      { group: "工作台", cmd: "/panel [help]", blurb: "打开科研工作台" },
      { group: "工作台", cmd: "/help", blurb: "打开本页" },
      { group: "能力", cmd: "/skill", blurb: "打开 Skill 管理页" },
      { group: "能力", cmd: "/skill:<name>", blurb: "显式调用已启用技能" },
      { group: "能力", cmd: "/agents [任务]", blurb: "浏览或运行 Subagent" },
      { group: "能力", cmd: "/ars [任务|doctor|stop]", blurb: "学术模式；尾随任务启动完整流程" },
      { group: "配置", cmd: "/provider [id]", blurb: "查看或切换模型 Provider" },
      { group: "配置", cmd: "/mcp", blurb: "打开 MCP 管理页" },
      { group: "配置", cmd: "/plugin", blurb: "打开 Plugin 管理页" },
      { group: "其他", cmd: "/export", blurb: "导出会话" },
      { group: "其他", cmd: "/pet [on|off]", blurb: "启动横幅宠物" },
    ],
    notes: [
      "斜杠命令采用 Codex 风格：单独命令，或命令 + 尾随自由文本；不用子命令树。",
      "/crosscheck = 过程性 AI 核对；/verify = 整体性 AI 验证。人审由收尾门禁自动要求（Panel/唤醒选项）。",
      "analysis / academic 收尾前须人审；/handoff 与定稿会拦。",
      "ARS / Nature / 写作与 analysis-plan、academic-grill 已随 npm 包提供。",
      "完整说明见仓库 docs/使用白皮书.md。",
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
  const groups = new Map<string, Array<{ cmd: string; blurb: string }>>();
  for (const row of doc.commands) {
    const key = row.group || "其他";
    const list = groups.get(key) ?? [];
    list.push(row);
    groups.set(key, list);
  }
  const commandBlocks = [...groups.entries()].flatMap(([group, rows]) => [
    `### ${group}`,
    ...rows.map((row) => `- \`${row.cmd}\` — ${row.blurb}`),
    "",
  ]);
  return [
    `# ${doc.title}`,
    doc.subtitle,
    "",
    "## 三种模式（Shift+Tab）",
    ...doc.modes.map((mode) => `- **${mode.label}** (\`${mode.hint}\`)：${mode.blurb}`),
    "",
    doc.thinking,
    "",
    "## 建议流程",
    ...doc.steps.map((step, index) => `${index + 1}. ${step}`),
    "",
    "## 常用命令",
    ...commandBlocks,
    "## 说明",
    ...doc.notes.map((note) => `- ${note}`),
  ].join("\n");
}
