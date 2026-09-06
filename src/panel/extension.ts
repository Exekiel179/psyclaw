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

function openWorkbench(url: string): Promise<boolean> {
  return new Promise((resolve) => {
    const command = process.platform === "win32" ? "cmd" : process.platform === "darwin" ? "open" : "xdg-open";
    const args = process.platform === "win32" ? ["/c", "start", "", url] : [url];
    let child;
    try {
      child = spawn(command, args, { detached: true, stdio: "ignore", windowsHide: true });
    } catch {
      resolve(false);
      return;
    }
    child.once("error", () => resolve(false));
    child.once("spawn", () => resolve(true));
    child.unref();
  });
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
          const next = createPanelServer(ctx.cwd, {
            assistant: async (message) => {
              pi.sendUserMessage(message, ctx.isIdle() ? {} : { deliverAs: "followUp" });
              return { text: "✓ 指令/提问已转入当前 PsyClaw 智能体并在终端会话中执行。" };
            },
            installSkill: async (task) => {
              pi.sendUserMessage(task, ctx.isIdle() ? {} : { deliverAs: "followUp" });
            },
            installExternalTool: async (task) => {
              pi.sendUserMessage(task, ctx.isIdle() ? {} : { deliverAs: "followUp" });
            },
            installPlugin: async (source, scope) => {
              await packageManager().installAndPersist(source, { local: scope === "project" });
            },
            listPlugins: () => packageManager().listConfiguredPackages().map(({ source, scope, filtered, installedPath }) => ({
              source,
              scope,
              filtered,
              installed: installedPath !== undefined,
            })),
          });
          const actualPort = await listen(next, 0);
          server = next;
          workbenchUrl = `http://127.0.0.1:${actualPort}`;
        }
        openWorkbench(workbenchUrl).then((opened) => {
          if (opened) {
            ctx.ui.notify(`科研工作台已在浏览器中打开：${workbenchUrl}`, "info");
          } else {
            // The local server is up regardless; give the user a reachable
            // fallback instead of leaving them with a dead-end error.
            ctx.ui.notify(`科研工作台已启动，但未能自动打开浏览器。请手动访问：${workbenchUrl}`, "warning");
          }
        }).catch((error) => {
          ctx.ui.notify(`科研工作台已启动，但自动打开失败：${error instanceof Error ? error.message : String(error)}。请手动访问：${workbenchUrl}`, "warning");
        });
      } catch (error) {
        server = undefined;
        workbenchUrl = undefined;
        const detail = error instanceof Error ? error.message : String(error);
        ctx.ui.notify(`科研工作台启动失败：${detail}`, "error");
      }
    },
  });

  pi.on("session_shutdown", async () => {
    await close();
  });
}
