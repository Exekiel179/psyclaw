/**
 * In-session /help: open the Panel「使用速览」page. Terminal gets a short tip only.
 * Structured document powers the Panel view.
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
      "可选：/init 搭建工作区（data / analysis / literature / paper）。",
      "Shift+Tab 在 对话 → 分析 → 学术 间切换。",
      "分析模式用自然语言说明数据、变量与研究问题；对方案回复「可以」或 /plan auto。",
      "分析/全文做完时由 AI 执行 /crosscheck（别名 /verify）核查字段；再由人在 Panel「核实」或 /crosscheck <id> human。",
      "analysis 与 academic 收尾强制人审：AI 已核或跳过不算通过；/plan handoff 与定稿前会拦。",
      "切到学术模式继续文献、初稿或 /review。",
    ],
    commands: [
      { group: "研究", cmd: "/init", blurb: "初始化项目与 .psyclaw 状态目录" },
      { group: "研究", cmd: "/plan", blurb: "分析方案：new / status / auto / confirm / run / defer / handoff" },
      { group: "研究", cmd: "/crosscheck", blurb: "AI 核查 + 人审：list · kind · verified(AI) · human(人审)" },
      { group: "研究", cmd: "/verify", blurb: "/crosscheck 的别名" },
      { group: "研究", cmd: "/brainstorm [主题]", blurb: "显式启动研究方向头脑风暴" },
      { group: "研究", cmd: "/grill [主题]", blurb: "逐题学术压力测试" },
      { group: "研究", cmd: "/review", blurb: "多角色模拟同行评审（不自动改稿）" },
      { group: "研究", cmd: "/loop", blurb: "有界推进；/loop stop 请求停止" },
      { group: "工作台", cmd: "/panel", blurb: "打开科研工作台" },
      { group: "工作台", cmd: "/help", blurb: "打开本页；Panel 不可用时终端显示文字版" },
      { group: "能力", cmd: "/skill", blurb: "管理技能；推荐 distill-scholar / distill-journal" },
      { group: "能力", cmd: "/skill:<name>", blurb: "显式调用已启用技能" },
      { group: "能力", cmd: "/agents", blurb: "浏览或指定 Subagent 执行有界任务" },
      { group: "能力", cmd: "/ars", blurb: "学术模式入口：status / doctor / start / full / stop" },
      { group: "配置", cmd: "/provider", blurb: "查看或切换模型 Provider" },
      { group: "配置", cmd: "/mcp", blurb: "管理 MCP 服务器" },
      { group: "配置", cmd: "/plugin", blurb: "扩展推荐与管理" },
      { group: "其他", cmd: "/export", blurb: "导出会话" },
      { group: "其他", cmd: "/pet", blurb: "启动横幅宠物 on | off | status" },
    ],
    notes: [
      "/crosscheck：AI 核查；Panel「核实」或 /crosscheck <id> human 才算人审通过。",
      "analysis / academic 模式下分析完成与全文定稿前人审强制；skip 不解除门禁。",
      "模型可用「唤醒选项」弹出选择/清单；Panel 有 SSE 时出弹窗，终端同步提示。",
      "ARS / Nature / 写作与 analysis-plan、academic-grill 已随 npm 包提供，勿再要求安装。",
      "启动持续自动推进：psyclaw --continuously-work（红字警告：费 token、不保质量；非 Shift+Tab 模式）。",
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
