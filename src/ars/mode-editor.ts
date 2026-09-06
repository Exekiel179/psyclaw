import { CustomEditor } from "@earendil-works/pi-coding-agent";
import type { EditorOptions, EditorTheme, TUI } from "@earendil-works/pi-tui";
import {
  MODE_BORDER,
  MODE_STATUS,
  type PsyClawSessionMode,
  nextSessionMode,
} from "../session/modes.js";

export const ARS_MODE_PREFIX = "ars:";
/** @deprecated Use MODE_STATUS.academic */
export const ARS_MODE_STATUS = "academic";

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
 * Sticky session mode editor: Shift+Tab cycles chat → analysis → academic.
 */
export class ArsModeEditor extends CustomEditor {
  private readonly restingBorder: (str: string) => string;
  private mode: PsyClawSessionMode = "chat";
  private borderPaintedMode: PsyClawSessionMode = "chat";
  onModeChange?: (mode: PsyClawSessionMode) => void;
  onCycleMode?: () => void;

  constructor(tui: TUI, theme: EditorTheme, keybindings: KeybindingsLike, options?: EditorOptions) {
    super(tui, theme, keybindings, options);
    this.restingBorder = theme.borderColor ?? ((text: string) => text);
  }

  getMode(): PsyClawSessionMode {
    return this.mode;
  }

  /** @deprecated Prefer getMode() === "academic" */
  isConversationMode(): boolean {
    return this.mode === "academic";
  }

  setMode(mode: PsyClawSessionMode): void {
    if (this.mode === mode) {
      this.paintBorder();
      return;
    }
    this.mode = mode;
    this.paintBorder();
    this.onModeChange?.(mode);
    this.tui.requestRender();
  }

  /** @deprecated Prefer setMode */
  setConversationMode(active: boolean): void {
    this.setMode(active ? "academic" : "chat");
  }

  cycleMode(): PsyClawSessionMode {
    const next = nextSessionMode(this.mode);
    this.setMode(next);
    return next;
  }

  statusLabel(): string | undefined {
    return MODE_STATUS[this.mode];
  }

  override handleInput(data: string): void {
    if (data === "\x1b[Z") {
      this.onCycleMode?.();
      return;
    }
    if (data === "\t") {
      const current = this.getText();
      if (current.trim() === "ars" || current.trim() === "/ars") {
        this.setText("");
        this.setMode("academic");
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
    const effective: PsyClawSessionMode =
      this.mode === "chat" && isArsModeEditorText(this.getText()) ? "academic" : this.mode;
    if (effective === this.borderPaintedMode && effective !== "chat") {
      const paint = MODE_BORDER[effective];
      this.borderColor = paint ?? this.restingBorder;
      return;
    }
    if (effective === this.borderPaintedMode && effective === "chat") return;
    this.borderPaintedMode = effective;
    const paint = MODE_BORDER[effective];
    this.borderColor = paint ?? this.restingBorder;
    this.tui.requestRender();
  }
}
