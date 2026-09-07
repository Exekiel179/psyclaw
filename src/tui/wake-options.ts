import type { KeybindingsManager, TUI } from "@earendil-works/pi-tui";
import { matchesKey, truncateToWidth } from "@earendil-works/pi-tui";
import type { Theme } from "@earendil-works/pi-coding-agent";
import type { WakeOptionItem, WakeOptionsMode } from "../panel/hub.js";

export type WakeOptionsUiResult =
  | { type: "submit"; selectedIds: string[] }
  | { type: "cancel" };

const MAX_VISIBLE = 9;

/**
 * CLI renderer for psyclaw_wake_options — choice (radio) or checklist (toggle).
 */
export class WakeOptionsComponent {
  focused = false;
  private selectedIndex = 0;
  private readonly checked = new Set<string>();
  private completed = false;

  constructor(
    private readonly title: string,
    private readonly prompt: string | undefined,
    private readonly mode: WakeOptionsMode,
    private readonly items: WakeOptionItem[],
    private readonly allowMultiple: boolean,
    private readonly minSelections: number,
    private readonly tui: TUI,
    private readonly theme: Theme,
    private readonly keybindings: KeybindingsManager,
    private readonly done: (result: WakeOptionsUiResult) => void,
  ) {
    for (const item of items) {
      if (item.checked) this.checked.add(item.id);
    }
    if (mode === "choice" && this.checked.size === 0 && items[0]) {
      this.checked.add(items[0].id);
    }
  }

  invalidate(): void {}

  render(width: number): string[] {
    const contentWidth = Math.max(28, width - 4);
    const start = Math.min(
      Math.max(0, this.selectedIndex - Math.floor(MAX_VISIBLE / 2)),
      Math.max(0, this.items.length - MAX_VISIBLE),
    );
    const visible = this.items.slice(start, start + MAX_VISIBLE);
    const lines = [
      this.theme.fg("accent", this.theme.bold(`唤醒选项 · ${this.title}`)),
      "",
    ];
    if (this.prompt) {
      lines.push(truncateToWidth(this.prompt, contentWidth), "");
    }
    for (const [offset, item] of visible.entries()) {
      const index = start + offset;
      const focused = index === this.selectedIndex;
      const on = this.checked.has(item.id);
      const marker = this.mode === "checklist" || this.allowMultiple
        ? (on ? "[x]" : "[ ]")
        : (on ? "(•)" : "( )");
      const pointer = focused ? this.theme.fg("accent", ">") : " ";
      const label = `${pointer} ${marker} ${item.label}`;
      lines.push(focused ? this.theme.bold(truncateToWidth(label, contentWidth)) : truncateToWidth(label, contentWidth));
      if (item.description && focused) {
        lines.push(this.theme.fg("dim", truncateToWidth(`    ${item.description}`, contentWidth)));
      }
    }
    if (this.items.length > MAX_VISIBLE) {
      lines.push(this.theme.fg("dim", `  ${this.selectedIndex + 1}/${this.items.length}`));
    }
    const hint = this.mode === "checklist" || this.allowMultiple
      ? "↑/↓ 移动 · Space 勾选 · Enter 提交 · Esc 取消"
      : "↑/↓ 移动 · Enter 确认 · Esc 取消";
    lines.push("", this.theme.fg("dim", hint));
    return lines;
  }

  handleInput(data: string): void {
    if (this.completed) return;
    if (this.keybindings.matches(data, "tui.select.cancel")) {
      this.completed = true;
      this.done({ type: "cancel" });
      return;
    }
    if (this.items.length === 0) return;
    if (this.keybindings.matches(data, "tui.select.up") || matchesKey(data, "k")) {
      this.selectedIndex = (this.selectedIndex - 1 + this.items.length) % this.items.length;
      this.tui.requestRender();
      return;
    }
    if (this.keybindings.matches(data, "tui.select.down") || matchesKey(data, "j")) {
      this.selectedIndex = (this.selectedIndex + 1) % this.items.length;
      this.tui.requestRender();
      return;
    }
    if (data === " " || matchesKey(data, "space")) {
      this.toggleCurrent();
      this.tui.requestRender();
      return;
    }
    if (this.keybindings.matches(data, "tui.select.confirm")) {
      if (this.mode === "choice" && !this.allowMultiple) {
        const current = this.items[this.selectedIndex];
        if (!current) return;
        this.completed = true;
        this.done({ type: "submit", selectedIds: [current.id] });
        return;
      }
      if (this.checked.size < this.minSelections) {
        return;
      }
      this.completed = true;
      this.done({ type: "submit", selectedIds: [...this.checked] });
    }
  }

  private toggleCurrent(): void {
    const current = this.items[this.selectedIndex];
    if (!current) return;
    if (this.mode === "choice" && !this.allowMultiple) {
      this.checked.clear();
      this.checked.add(current.id);
      return;
    }
    if (this.checked.has(current.id)) this.checked.delete(current.id);
    else this.checked.add(current.id);
  }
}
