import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { closeResearchWorkbench, openResearchWorkbench } from "./workbench.js";

/**
 * Optional Pi extension for the local web projection. Binding is always loopback.
 */
export default function psyclawPanelExtension(pi: ExtensionAPI): void {
  pi.registerCommand("panel", {
    description: "打开科研工作台（浏览器）",
    handler: async (args, ctx) => {
      const trimmed = args.trim().toLowerCase();
      if (trimmed && trimmed !== "help" && !trimmed.startsWith("view=")) {
        ctx.ui.notify("用法：/panel 或 /panel help", "info");
        return;
      }
      const view = trimmed === "help" || trimmed === "view=help" ? "help" : undefined;
      try {
        const { url, opened } = await openResearchWorkbench({
          cwd: ctx.cwd,
          isProjectTrusted: () => ctx.isProjectTrusted(),
          isIdle: () => ctx.isIdle(),
          sendUserMessage: (message, options) => pi.sendUserMessage(message, options ?? {}),
        }, view ? { view } : {});
        ctx.ui.notify(
          opened ? `科研工作台已打开：${url}` : `工作台已启动，请手动访问：${url}`,
          opened ? "info" : "warning",
        );
      } catch (error) {
        const detail = error instanceof Error ? error.message : String(error);
        ctx.ui.notify(`科研工作台启动失败：${detail}`, "error");
      }
    },
  });

  pi.on("session_shutdown", async () => {
    await closeResearchWorkbench();
  });
}
