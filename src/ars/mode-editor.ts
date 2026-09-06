import { CustomEditor } from "@earendil-works/pi-coding-agent";
import type { EditorOptions, EditorTheme, TUI } from "@earendil-works/pi-tui";

/** Match PsyClaw accent (#2ec4b6) for the ARS conversation-mode border. */
const ARS_BORDER = (text: string): string => `\x1b[38;2;46;196;182m${text}\x1b[39m`;

export const ARS_MODE_PREFIX = "ars:";

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
 * Pi CustomEditor that turns bare `ars` + Tab into `ars:` conversation mode
 * (tinted border), similar to bash mode's `!` prefix UX.
 */
export class ArsModeEditor extends CustomEditor {
  private readonly restingBorder: (str: string) => string;
  private arsBorderActive = false;
  onArsModeChange?: (active: boolean) => void;

  constructor(tui: TUI, theme: EditorTheme, keybindings: KeybindingsLike, options?: EditorOptions) {
    super(tui, theme, keybindings, options);
    this.restingBorder = theme.borderColor ?? ((text: string) => text);
  }

  override handleInput(data: string): void {
    if (data === "\t") {
      const current = this.getText();
      if (current.trim() === "ars" || current.trim() === "/ars") {
        this.setText(enterArsModeEditorText(current));
        this.syncArsBorder();
        return;
      }
    }
    super.handleInput(data);
    this.syncArsBorder();
  }

  override setText(text: string): void {
    super.setText(text);
    this.syncArsBorder();
  }

  private syncArsBorder(): void {
    const active = isArsModeEditorText(this.getText());
    if (active === this.arsBorderActive) {
      if (active) this.borderColor = ARS_BORDER;
      return;
    }
    this.arsBorderActive = active;
    this.borderColor = active ? ARS_BORDER : this.restingBorder;
    this.onArsModeChange?.(active);
    this.tui.requestRender();
  }
}
