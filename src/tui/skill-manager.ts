import type { KeybindingsManager, TUI } from "@earendil-works/pi-tui";
import { Key, matchesKey, truncateToWidth } from "@earendil-works/pi-tui";
import type { Theme } from "@earendil-works/pi-coding-agent";

export type SkillManagerStatus = "core" | "enabled" | "disabled" | "missing" | "blocked";

export interface SkillManagerItem {
  id: string;
  name: string;
  description: string;
  status: SkillManagerStatus;
  sourceRef?: string;
  reason?: string;
  details?: string[];
  configuredEnabled?: boolean;
}

export interface SkillManagerOptions {
  title?: string;
  itemLabel?: string;
  lockedMessage?: string;
  missingMessage?: string;
  footer?: string;
  enterAction?: "details" | "install";
  enabledText?: string;
  disabledText?: string;
  blockedText?: string;
}

export type SkillManagerAction =
  | { type: "close" }
  | { type: "toggle"; id: string; enabled: boolean }
  | { type: "toggle-all"; enabled: boolean }
  | { type: "install"; id: string };

const MAX_VISIBLE = 10;

function statusLabel(status: SkillManagerStatus): string {
  if (status === "core") return "[◆]";
  if (status === "enabled") return "[●]";
  if (status === "disabled") return "[ ]";
  if (status === "missing") return "[↓]";
  return "[!]";
}

function statusText(status: SkillManagerStatus, options: SkillManagerOptions): string {
  if (status === "core") return "内置，始终启用";
  if (status === "enabled") return options.enabledText ?? "已启用，重启后按此配置加载";
  if (status === "disabled") return options.disabledText ?? "已安装，当前未启用";
  if (status === "missing") return "尚未安装";
  return options.blockedText ?? "预检阻断";
}

export class SkillManagerComponent {
  focused = false;
  private selectedIndex = 0;
  private notice = "";

  constructor(
    private readonly items: SkillManagerItem[],
    private readonly tui: TUI,
    private readonly theme: Theme,
    private readonly keybindings: KeybindingsManager,
    private readonly done: (action: SkillManagerAction) => void,
    private readonly options: SkillManagerOptions = {},
  ) {}

  invalidate(): void {}

  render(width: number): string[] {
    const contentWidth = Math.max(24, width - 4);
    const enabled = this.items.filter((item) => item.status === "core" || item.status === "enabled").length;
    const issues = this.items.filter((item) => item.status === "blocked").length;
    const selected = this.items[this.selectedIndex];
    const start = Math.min(
      Math.max(0, this.selectedIndex - Math.floor(MAX_VISIBLE / 2)),
      Math.max(0, this.items.length - MAX_VISIBLE),
    );
    const visible = this.items.slice(start, start + MAX_VISIBLE);
    const lines = [
      this.theme.fg("accent", this.theme.bold(this.options.title ?? "Skill 管理")),
      this.theme.fg("dim", `${enabled} 个启用 · ${this.items.length - enabled - issues} 个可管理 · ${issues} 个需处理`),
      "",
    ];

    for (const [offset, item] of visible.entries()) {
      const active = start + offset === this.selectedIndex;
      const prefix = active ? this.theme.fg("accent", ">") : " ";
      const state = item.status === "blocked"
        ? this.theme.fg("warning", statusLabel(item.status))
        : item.status === "enabled" || item.status === "core"
          ? this.theme.fg("success", statusLabel(item.status))
          : this.theme.fg("muted", statusLabel(item.status));
      const label = `${prefix} ${state} ${item.name}`;
      lines.push(active ? this.theme.bold(truncateToWidth(label, contentWidth)) : truncateToWidth(label, contentWidth));
    }

    if (selected) {
      lines.push(
        "",
        this.theme.fg("borderMuted", "─".repeat(Math.max(1, Math.min(contentWidth, 72)))),
        this.theme.bold(truncateToWidth(selected.name, contentWidth)),
        this.theme.fg("muted", truncateToWidth(statusText(selected.status, this.options), contentWidth)),
        truncateToWidth(selected.description || "暂无说明", contentWidth),
      );
      if (selected.sourceRef) lines.push(this.theme.fg("dim", truncateToWidth(`来源：${selected.sourceRef}`, contentWidth)));
      for (const detail of selected.details ?? []) lines.push(this.theme.fg("dim", truncateToWidth(detail, contentWidth)));
      if (selected.reason) lines.push(this.theme.fg("warning", truncateToWidth(`原因：${selected.reason}`, contentWidth)));
    }
    if (this.notice) lines.push("", this.theme.fg("warning", truncateToWidth(this.notice, contentWidth)));
    lines.push("", this.theme.fg("dim", this.options.footer ?? "↑/↓ 移动 · Space 启用/停用 · a 全部启用 · d 全部停用 · Enter 查看/安装 · Esc 关闭"));
    return lines;
  }

  handleInput(data: string): void {
    if (this.items.length === 0) {
      if (this.keybindings.matches(data, "tui.select.cancel")) this.done({ type: "close" });
      return;
    }
    if (this.keybindings.matches(data, "tui.select.cancel")) {
      this.done({ type: "close" });
      return;
    }
    if (this.keybindings.matches(data, "tui.select.up") || matchesKey(data, "k")) {
      this.selectedIndex = (this.selectedIndex - 1 + this.items.length) % this.items.length;
      this.notice = "";
      this.tui.requestRender();
      return;
    }
    if (this.keybindings.matches(data, "tui.select.down") || matchesKey(data, "j")) {
      this.selectedIndex = (this.selectedIndex + 1) % this.items.length;
      this.notice = "";
      this.tui.requestRender();
      return;
    }

    // Batch operations: `a` enables every manageable item, `d` disables every
    // manageable item. Core and blocked items are skipped by the handler.
    if (matchesKey(data, "a")) {
      this.done({ type: "toggle-all", enabled: true });
      return;
    }
    if (matchesKey(data, "d")) {
      this.done({ type: "toggle-all", enabled: false });
      return;
    }

    const item = this.items[this.selectedIndex]!;
    if (matchesKey(data, Key.space)) {
      if (item.status === "core") this.notice = this.options.lockedMessage ?? "核心 Skill 始终启用，不能在这里停用。";
      else if (item.status === "blocked" && item.configuredEnabled === true) this.done({ type: "toggle", id: item.id, enabled: false });
      else if (item.status === "blocked") this.notice = item.reason ?? `该 ${this.options.itemLabel ?? "Skill"} 未通过来源、许可或依赖预检。`;
      else if (item.status === "missing") this.notice = this.options.missingMessage ?? "按 Enter 查看固定来源并确认安装。";
      else this.done({ type: "toggle", id: item.id, enabled: item.status === "disabled" });
      this.tui.requestRender();
      return;
    }
    if (this.keybindings.matches(data, "tui.select.confirm")) {
      if (item.status === "missing" || this.options.enterAction === "install") {
        this.done({ type: "install", id: item.id });
        return;
      }
      if (item.status === "blocked") this.notice = item.reason ?? `该 ${this.options.itemLabel ?? "Skill"} 未通过来源、许可或依赖预检。`;
      else if (item.status === "core") this.notice = "这是 PsyClaw 核心 Skill，始终加载且不会被同名第三方 Skill 覆盖。";
      else this.notice = item.sourceRef ? `固定来源：${item.sourceRef}` : "该 Skill 没有可显示的来源信息。";
      this.tui.requestRender();
    }
  }
}
