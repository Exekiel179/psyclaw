import type { KeybindingsManager, TUI } from "@earendil-works/pi-tui";
import { matchesKey, truncateToWidth } from "@earendil-works/pi-tui";
import type { Theme } from "@earendil-works/pi-coding-agent";

export interface BiosignalWizardDomain {
  id: string;
  name: string;
  description: string;
}

export interface BiosignalWizardPlanSummary {
  domainNames: string[];
  mcpIds: string[];
  skillIds: string[];
}

export type BiosignalWizardResult =
  | { type: "close" }
  | { type: "confirm"; domainIds: string[] };

type WizardPhase = "select" | "confirm";

const MAX_VISIBLE = 8;

/**
 * Two-step pack wizard: multi-select research domains, then confirm the
 * resolved MCP + Skill install list. Space toggles; Enter advances/confirms.
 */
export class BiosignalWizardComponent {
  focused = false;
  private phase: WizardPhase = "select";
  private selectedIndex = 0;
  private readonly selected = new Set<string>();
  private completed = false;
  private plan: BiosignalWizardPlanSummary | undefined;
  private notice = "";

  constructor(
    private readonly domains: BiosignalWizardDomain[],
    private readonly resolvePlan: (domainIds: string[]) => BiosignalWizardPlanSummary,
    private readonly tui: TUI,
    private readonly theme: Theme,
    private readonly keybindings: KeybindingsManager,
    private readonly done: (result: BiosignalWizardResult) => void,
  ) {}

  invalidate(): void {}

  render(width: number): string[] {
    const contentWidth = Math.max(24, width - 4);
    if (this.phase === "confirm" && this.plan) {
      return this.renderConfirm(contentWidth);
    }
    return this.renderSelect(contentWidth);
  }

  private renderSelect(contentWidth: number): string[] {
    const start = Math.min(
      Math.max(0, this.selectedIndex - Math.floor(MAX_VISIBLE / 2)),
      Math.max(0, this.domains.length - MAX_VISIBLE),
    );
    const visible = this.domains.slice(start, start + MAX_VISIBLE);
    const lines = [
      this.theme.fg("accent", this.theme.bold("生理信号分析 · 选择研究域")),
      this.theme.fg("dim", "可多选；装好后仍在 analysis 模式中使用，不是第四种 Shift+Tab 模式。"),
      "",
    ];
    for (const [offset, domain] of visible.entries()) {
      const active = start + offset === this.selectedIndex;
      const checked = this.selected.has(domain.id);
      const marker = active ? this.theme.fg("accent", ">") : " ";
      const box = checked ? this.theme.fg("success", "[✓]") : this.theme.fg("muted", "[ ]");
      const label = `${marker} ${box} ${domain.name}`;
      lines.push(active ? this.theme.bold(truncateToWidth(label, contentWidth)) : truncateToWidth(label, contentWidth));
    }
    const focused = this.domains[this.selectedIndex];
    if (focused?.description) {
      lines.push("", this.theme.fg("dim", truncateToWidth(focused.description, contentWidth)));
    }
    if (this.notice) lines.push("", this.theme.fg("warning", this.notice));
    lines.push(
      "",
      this.theme.fg("dim", `已选 ${this.selected.size} 项 · ↑/↓ 移动 · Space 勾选 · Enter 下一步 · Esc 取消`),
    );
    return lines;
  }

  private renderConfirm(contentWidth: number): string[] {
    const plan = this.plan!;
    const lines = [
      this.theme.fg("accent", this.theme.bold("生理信号分析 · 确认安装清单")),
      this.theme.fg("dim", `研究域：${plan.domainNames.join("、")}`),
      "",
      this.theme.bold("将安装 / 配置："),
    ];
    if (plan.mcpIds.length === 0 && plan.skillIds.length === 0) {
      lines.push(this.theme.fg("warning", "  （空清单）"));
    } else {
      for (const id of plan.mcpIds) {
        lines.push(truncateToWidth(`  MCP  ${id}`, contentWidth));
      }
      for (const id of plan.skillIds) {
        lines.push(truncateToWidth(`  Skill  ${id}`, contentWidth));
      }
    }
    lines.push(
      "",
      this.theme.fg("dim", "确认后交给当前模型，按现有 /mcp 与 /skill 安装约定完成配置。"),
      this.theme.fg("dim", "Enter 开始安装 · Esc 返回选型"),
    );
    return lines;
  }

  handleInput(data: string): void {
    if (this.completed) return;
    if (this.keybindings.matches(data, "tui.select.cancel")) {
      if (this.phase === "confirm") {
        this.phase = "select";
        this.plan = undefined;
        this.notice = "";
        this.tui.requestRender();
        return;
      }
      this.completed = true;
      this.done({ type: "close" });
      return;
    }
    if (this.phase === "confirm") {
      if (this.keybindings.matches(data, "tui.select.confirm")) {
        this.completed = true;
        this.done({ type: "confirm", domainIds: [...this.selected] });
      }
      return;
    }
    if (this.domains.length === 0) return;
    if (this.keybindings.matches(data, "tui.select.up") || matchesKey(data, "k")) {
      this.selectedIndex = (this.selectedIndex - 1 + this.domains.length) % this.domains.length;
      this.tui.requestRender();
      return;
    }
    if (this.keybindings.matches(data, "tui.select.down") || matchesKey(data, "j")) {
      this.selectedIndex = (this.selectedIndex + 1) % this.domains.length;
      this.tui.requestRender();
      return;
    }
    if (data === " ") {
      const id = this.domains[this.selectedIndex]?.id;
      if (!id) return;
      if (this.selected.has(id)) this.selected.delete(id);
      else this.selected.add(id);
      this.notice = "";
      this.tui.requestRender();
      return;
    }
    if (this.keybindings.matches(data, "tui.select.confirm")) {
      if (this.selected.size === 0) {
        this.notice = "请先用 Space 勾选至少一个研究域";
        this.tui.requestRender();
        return;
      }
      try {
        this.plan = this.resolvePlan([...this.selected]);
        this.phase = "confirm";
        this.notice = "";
        this.tui.requestRender();
      } catch (error) {
        this.notice = error instanceof Error ? error.message : String(error);
        this.tui.requestRender();
      }
    }
  }
}
