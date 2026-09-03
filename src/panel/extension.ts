import type { Server } from "node:http";
import { spawn } from "node:child_process";
import { DefaultPackageManager, getAgentDir, SettingsManager, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { createPanelServer } from "./server.js";

async function listen(server: Server, port: number): Promise<number> {
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => resolve());
  });
  const address = server.address();
  return typeof address === "object" && address !== null ? address.port : port;
}

function openWorkbench(url: string): void {
  const command = process.platform === "win32" ? "cmd" : process.platform === "darwin" ? "open" : "xdg-open";
  const args = process.platform === "win32" ? ["/c", "start", "", url] : [url];
  const child = spawn(command, args, { detached: true, stdio: "ignore", windowsHide: true });
  child.on("error", () => undefined);
  child.unref();
}

/**
 * Optional Pi extension for the local, read-only web projection. The core
 * psyclaw package does not load this extension by default; `/agents` remains a
 * native core command. Binding is always loopback and the panel has no write
 * endpoint.
 */
export default function psyclawPanelExtension(pi: ExtensionAPI): void {
  let server: Server | undefined;
  let workbenchUrl: string | undefined;

  const close = async (): Promise<void> => {
    const current = server;
    server = undefined;
    workbenchUrl = undefined;
    if (!current) return;
    await new Promise<void>((resolve) => current.close(() => resolve()));
  };

  pi.registerCommand("panel", {
    description: "Open the psyclaw research workbench in your browser",
    handler: async (args, ctx) => {
      if (args.trim() !== "") {
        ctx.ui.notify("直接输入 /panel 即可打开科研工作台", "info");
        return;
      }
      try {
        if (server === undefined || workbenchUrl === undefined) {
          const packageManager = (): DefaultPackageManager => new DefaultPackageManager({
            cwd: ctx.cwd,
            agentDir: getAgentDir(),
            settingsManager: SettingsManager.create(ctx.cwd, getAgentDir(), { projectTrusted: ctx.isProjectTrusted() }),
          });
          const next = createPanelServer(ctx.cwd, { installSkill: async (task) => {
            pi.sendUserMessage(task, ctx.isIdle() ? {} : { deliverAs: "followUp" });
          }, installExternalTool: async (task) => {
            pi.sendUserMessage(task, ctx.isIdle() ? {} : { deliverAs: "followUp" });
          }, installPlugin: async (source, scope) => {
            await packageManager().installAndPersist(source, { local: scope === "project" });
          }, listPlugins: () => packageManager().listConfiguredPackages().map(({ source, scope, filtered, installedPath }) => ({
            source,
            scope,
            filtered,
            installed: installedPath !== undefined,
          })) });
          const actualPort = await listen(next, 0);
          server = next;
          workbenchUrl = `http://127.0.0.1:${actualPort}`;
        }
        openWorkbench(workbenchUrl);
        ctx.ui.notify(`科研工作台已在浏览器中打开：${workbenchUrl}`, "info");
      } catch (error) {
        server = undefined;
        workbenchUrl = undefined;
        ctx.ui.notify(error instanceof Error ? error.message : "科研工作台暂时无法打开", "error");
      }
    },
  });

  pi.on("session_shutdown", async () => {
    await close();
  });
}
