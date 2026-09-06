import { CustomEditor } from "@earendil-works/pi-coding-agent";
import type { EditorOptions, EditorTheme, TUI } from "@earendil-works/pi-tui";

/** Match PsyClaw accent (#2ec4b6) for the ARS conversation-mode border. */
const ARS_BORDER = (text: string): string => `\x1b[38;2;46;196;182m${text}\x1b[39m`;

export const ARS_MODE_PREFIX = "ars:";
export const ARS_MODE_STATUS = "academic mode";

export function isArsModeEditorText(text: string): boolean {
  return /^ars:/i.test(text.trimStart());
}

export function enterArsModeEditorText(existing = ""): string {
  const trimmed = existing.trim();
  if (!trimmed || trimmed === "ars" || trimmed === "/ars") return `${ARS_MODE_PREFIX} `;
  if (isArsModeEditorText(existing)) return existing;
  return `${ARS_MODE_PREFIX} ${trimmed}`;
}

type KeybindingsLike = ConstructorParameters<typeof CustomEditor>[2];

/**
 * Sticky academic conversation mode: Shift+Tab toggles tinted border + footer
 * "academic mode". Messages then use the session ARS state without a per-turn prefix.
 */
export class ArsModeEditor extends CustomEditor {
  private readonly restingBorder: (str: string) => string;
  private conversationMode = false;
  private borderPainted = false;
  onArsModeChange?: (active: boolean) => void;
  onToggleConversationMode?: () => void;

  constructor(tui: TUI, theme: EditorTheme, keybindings: KeybindingsLike, options?: EditorOptions) {
    super(tui, theme, keybindings, options);
    this.restingBorder = theme.borderColor ?? ((text: string) => text);
  }

  isConversationMode(): boolean {
    return this.conversationMode;
  }

  setConversationMode(active: boolean): void {
    if (this.conversationMode === active) {
      this.paintBorder();
      return;
    }
    this.conversationMode = active;
    this.paintBorder();
    this.onArsModeChange?.(active);
    this.tui.requestRender();
  }

  override handleInput(data: string): void {
    // Shift+Tab — classic backtab sequence when Kitty protocol is off.
    if (data === "\x1b[Z") {
      this.onToggleConversationMode?.();
      return;
    }
    if (data === "\t") {
      const current = this.getText();
      if (current.trim() === "ars" || current.trim() === "/ars") {
        this.setText("");
        this.onToggleConversationMode?.();
        return;
      }
    }
    super.handleInput(data);
    this.paintBorder();
  }

  override setText(text: string): void {
    super.setText(text);
    this.paintBorder();
  }

  private paintBorder(): void {
    const active = this.conversationMode || isArsModeEditorText(this.getText());
    if (active === this.borderPainted && active) {
      this.borderColor = ARS_BORDER;
      return;
    }
    if (active === this.borderPainted && !active) return;
    this.borderPainted = active;
    this.borderColor = active ? ARS_BORDER : this.restingBorder;
    this.tui.requestRender();
  }
}
