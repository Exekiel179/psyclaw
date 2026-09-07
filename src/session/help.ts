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
      { id: "chat", label: "对话模式（chat）", blurb: "用于普通问答，也可以直接用自然语言请求研究、分析、写作或资料整理。" },
      { id: "analysis", label: "分析模式（analysis）", blurb: "围绕研究问题澄清、分析方案、可复现脚本、结果核对和分析报告逐步推进。" },
      { id: "academic", label: "学术模式（academic）", blurb: "用于文献研究、论文写作、格式完善和同行评审；相关能力会按请求自动调用。" },
    ],
    thinking: "思考深度：Ctrl+Shift+T（比 Ctrl+Shift+Tab 更可靠）",
    steps: [
      "使用 /init 搭建研究工作区；也可以稍后初始化。",
      "按需要使用 Shift+Tab 切换对话、分析和学术模式。",
      "在分析模式中用自然语言说明研究问题、数据、变量和希望回答的内容。",
      "系统会提出分析方案；你可以逐项选择，回复「可以」确认，或使用 /plan auto 采用自动确认。",
      "分析前后使用 /crosscheck 或 /verify 查看并完成交叉核验；跳过的项目会标记为「未经核对」。",
      "分析完成后，可切换到学术模式继续文献研究、写作或评审。",
    ],
    commands: [
      { cmd: "/init", blurb: "初始化研究项目，创建目录、项目说明和 .psyclaw 状态目录。" },
      { cmd: "/plan", blurb: "创建、查看、确认、运行、推迟或交接分析方案；可用 /plan status 查看进度。" },
      { cmd: "/crosscheck", blurb: "查看或更新交叉核验清单；支持 list、skip、kind 和按编号标记状态。" },
      { cmd: "/verify", blurb: "交叉核验的别名，与 /crosscheck 使用相同的清单和操作。" },
      { cmd: "/grill", blurb: "针对研究问题、设计、方法和论证进行逐题学术压力测试。" },
      { cmd: "/review", blurb: "运行多角色模拟同行评审；输出评审意见，不会自动修改稿件。" },
      { cmd: "/loop", blurb: "按当前研究目标有界推进一个研究阶段；使用 /loop stop 请求停止。" },
      { cmd: "/agents", blurb: "浏览可用的内置或项目多智能体，或使用 --agent 指定角色执行有边界的任务。" },
      { cmd: "/panel", blurb: "打开科研工作台，查看项目文件、运行状态、能力管理、模型配置和核对清单。" },
      { cmd: "/help", blurb: "打开本页使用速览；如果工作台无法启动，会在终端显示文字版说明。" },
      { cmd: "/skill", blurb: "查看、启用、停用或安装技能；使用 /skill install <local-directory> 安装本地技能。" },
      { cmd: "/skill:<name>", blurb: "直接调用指定技能；将 <name> 替换为要使用的技能名称。" },
      { cmd: "/ars", blurb: "切换到学术模式，或执行状态检查、启动、完整流程和停止操作。" },
      { cmd: "/ars-full", blurb: "启动完整学术研究流程；在命令后附上本次任务。" },
      { cmd: "/mcp", blurb: "查看、安装、启用、停用和检查外部工具服务及其可用工具。" },
      { cmd: "/plugin", blurb: "打开扩展推荐与管理页面，查看可发现的扩展及其状态。" },
      { cmd: "/provider", blurb: "查看、配置或切换模型服务提供方。" },
      { cmd: "/pet", blurb: "使用 on、off 或 status 开启、关闭或查看启动横幅中的宠物。" },
      { cmd: "/export", blurb: "使用 Pi 提供的会话导出功能保存当前对话。" },
      { cmd: "/create-skill", blurb: "预览并创建项目级技能；创建前会展示内容、路径和校验摘要。" },
      { cmd: "/create-hook", blurb: "预览并创建项目级分析 Hook，用于在分析生命周期节点发出提醒或阻断。" },
      { cmd: "/create-rule", blurb: "预览并创建项目级附加规则；规则不能覆盖系统研究门禁。" },
      { cmd: "/create-subagent", blurb: "预览并创建项目级协作智能体；默认只读，提升权限时需要确认。" },
      { cmd: "/model", blurb: "列出或切换当前模型；仅在启用开发命令时提供。" },
      { cmd: "/handoff", blurb: "生成机器可读的研究交接检查点；仅在启用开发命令时提供。" },
    ],
    notes: [
      "模型可以通过「唤醒选项」弹出选择框或核对清单；连接工作台时会显示为弹窗，终端中会同步提示。",
      "学术研究、论文写作、分析方案和学术压力测试能力均已随包提供；直接用自然语言描述需求即可调用，也可以使用对应的 /skill:<name>。",
      "可选的外部推荐能力不会默认执行；启用前请查看来源、版本、许可证、依赖和信任状态。",
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
