import type { KeybindingsManager, TUI } from "@earendil-works/pi-tui";
import { matchesKey, truncateToWidth } from "@earendil-works/pi-tui";
import type { Theme } from "@earendil-works/pi-coding-agent";

export interface ProviderPickerItem {
  id: string;
  label: string;
  description?: string;
  current?: boolean;
}

export type ProviderPickerResult = { type: "select"; id: string } | { type: "close" };

const MAX_VISIBLE = 7;

export class ProviderPickerComponent {
  focused = false;
  private selectedIndex: number;
  private completed = false;

  constructor(
    private readonly title: string,
    private readonly items: ProviderPickerItem[],
    private readonly tui: TUI,
    private readonly theme: Theme,
    private readonly keybindings: KeybindingsManager,
    private readonly done: (result: ProviderPickerResult) => void,
  ) {
    this.selectedIndex = Math.max(0, items.findIndex((item) => item.current));
  }

  invalidate(): void {}

  render(width: number): string[] {
    const contentWidth = Math.max(24, width - 4);
    const start = Math.min(
      Math.max(0, this.selectedIndex - Math.floor(MAX_VISIBLE / 2)),
      Math.max(0, this.items.length - MAX_VISIBLE),
    );
    const visible = this.items.slice(start, start + MAX_VISIBLE);
    const lines = [this.theme.fg("accent", this.theme.bold(this.title)), ""];
    for (const [offset, item] of visible.entries()) {
      const selected = start + offset === this.selectedIndex;
      const marker = selected ? this.theme.fg("accent", ">") : " ";
      const current = item.current ? this.theme.fg("success", " [当前]") : "";
      const label = `${marker} ${item.label}${current}`;
      lines.push(selected ? this.theme.bold(truncateToWidth(label, contentWidth)) : truncateToWidth(label, contentWidth));
      // Keep one row per item so the focused row remains visible in short
      // terminals; details are presented after selection.
    }
    if (this.items.length > MAX_VISIBLE) {
      lines.push(this.theme.fg("dim", `  ${this.selectedIndex + 1}/${this.items.length}`));
    }
    lines.push("", this.theme.fg("dim", "↑/↓ 移动 · Enter 确认 · Esc 关闭"));
    return lines;
  }

  handleInput(data: string): void {
    if (this.completed) return;
    if (this.keybindings.matches(data, "tui.select.cancel")) {
      this.completed = true;
      this.done({ type: "close" });
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
    if (this.keybindings.matches(data, "tui.select.confirm")) {
      this.completed = true;
      this.done({ type: "select", id: this.items[this.selectedIndex]!.id });
    }
  }
}

export type SecretInputResult = { type: "submit"; value: string } | { type: "close" };

export class SecretInputComponent {
  focused = false;
  private value = "";
  private completed = false;

  constructor(
    private readonly title: string,
    private readonly envName: string,
    private readonly tui: TUI,
    private readonly theme: Theme,
    private readonly keybindings: KeybindingsManager,
    private readonly done: (result: SecretInputResult) => void,
  ) {}

  invalidate(): void {}

  render(width: number): string[] {
    const contentWidth = Math.max(24, width - 4);
    const mask = this.value ? "•".repeat(Math.min(this.value.length, Math.max(8, contentWidth - 8))) : "（留空则使用已有本地 Key）";
    return [
      this.theme.fg("accent", this.theme.bold(this.title)),
      "",
      truncateToWidth(`API Key: ${mask}`, contentWidth),
      this.theme.fg("dim", `凭据名称：${this.envName}`),
      "",
      this.theme.fg("dim", "直接输入或粘贴 · Enter 保存 · Esc 返回"),
    ];
  }

  handleInput(data: string): void {
    if (this.completed) return;
    if (this.keybindings.matches(data, "tui.select.cancel")) {
      this.completed = true;
      this.done({ type: "close" });
      return;
    }
    if (this.keybindings.matches(data, "tui.input.submit") || data === "\n" || data === "\r") {
      this.completed = true;
      this.done({ type: "submit", value: this.value });
      return;
    }
    if (this.keybindings.matches(data, "tui.editor.deleteCharBackward")) {
      this.value = [...this.value].slice(0, -1).join("");
      this.tui.requestRender();
      return;
    }
    const pasted = data.replaceAll("\x1b[200~", "").replaceAll("\x1b[201~", "").replace(/[\r\n]/g, "");
    if (pasted && !/[\u0000-\u001f\u007f]/u.test(pasted)) {
      this.value += pasted;
      this.tui.requestRender();
    }
  }
}
