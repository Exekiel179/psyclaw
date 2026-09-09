import type { Server } from "node:http";
import { spawn } from "node:child_process";
import { DefaultPackageManager, getAgentDir, SettingsManager } from "@earendil-works/pi-coding-agent";
import { createPanelServer } from "./server.js";
import { panelHub } from "./hub.js";

let server: Server | undefined;
let workbenchUrl: string | undefined;

async function listen(next: Server, port: number): Promise<number> {
  await new Promise<void>((resolve, reject) => {
    next.once("error", reject);
    next.listen(port, "127.0.0.1", () => resolve());
  });
  const address = next.address();
  return typeof address === "object" && address !== null ? address.port : port;
}

function openBrowser(url: string): Promise<boolean> {
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

export type WorkbenchHost = {
  cwd: string;
  isProjectTrusted: () => boolean;
  isIdle: () => boolean;
  sendUserMessage: (message: string, options?: { deliverAs?: "followUp" }) => void;
};

/** Start or reuse the loopback workbench; optional `view` opens a named Panel page (e.g. help). */
export async function openResearchWorkbench(
  host: WorkbenchHost,
  options: { view?: string } = {},
): Promise<{ url: string; opened: boolean }> {
  if (server === undefined || workbenchUrl === undefined) {
    const packageManager = (): DefaultPackageManager => new DefaultPackageManager({
      cwd: host.cwd,
      agentDir: getAgentDir(),
      settingsManager: SettingsManager.create(host.cwd, getAgentDir(), { projectTrusted: host.isProjectTrusted() }),
    });
    const next = createPanelServer(host.cwd, {
      hub: panelHub,
      assistant: async (message) => {
        panelHub.broadcast({ type: "user_echo", text: message });
        host.sendUserMessage(message, host.isIdle() ? {} : { deliverAs: "followUp" });
        return {
          text: panelHub.hasPanelClients()
            ? "已转入当前会话；回复将通过 SSE 同步到本对话区。"
            : "已转入当前会话；请保持 Panel 打开以接收流式回复。",
        };
      },
      installSkill: async (task) => {
        host.sendUserMessage(task, host.isIdle() ? {} : { deliverAs: "followUp" });
      },
      installMcp: async (task) => {
        host.sendUserMessage(task, host.isIdle() ? {} : { deliverAs: "followUp" });
      },
      installExternalTool: async (task) => {
        host.sendUserMessage(task, host.isIdle() ? {} : { deliverAs: "followUp" });
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
  const target = options.view
    ? `${workbenchUrl}/#${encodeURIComponent(options.view)}`
    : workbenchUrl;
  const opened = await openBrowser(target);
  return { url: target, opened };
}

export async function closeResearchWorkbench(): Promise<void> {
  const current = server;
  server = undefined;
  workbenchUrl = undefined;
  if (!current) return;
  // SSE keep-alive clients otherwise keep server.close() pending forever.
  panelHub.disconnectAll();
  await new Promise<void>((resolve) => {
    const failsafe = setTimeout(() => {
      current.closeAllConnections();
      resolve();
    }, 1_000);
    current.close(() => {
      clearTimeout(failsafe);
      resolve();
    });
  });
}
