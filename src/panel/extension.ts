import type { Server } from "node:http";
import { spawn } from "node:child_process";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { createPanelServer } from "./server.js";
import { PiRpcClient } from "../adapters/pi/rpc.js";

function assistantEnv(provider: string | undefined): Record<string, string> {
  const envName = provider === "deepseek" ? "DEEPSEEK_API_KEY" : provider === "openai" ? "OPENAI_API_KEY" : provider === "anthropic" ? "ANTHROPIC_API_KEY" : provider === "google" ? "GEMINI_API_KEY" : undefined;
  const value = envName === undefined ? undefined : process.env[envName];
  return envName !== undefined && value !== undefined ? { [envName]: value } : {};
}

function assistantText(events: Array<Record<string, unknown>>): string {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event?.type !== "message_end" || !event.message || typeof event.message !== "object") continue;
    const content = (event.message as { content?: unknown }).content;
    if (!Array.isArray(content)) continue;
    const text = content.filter((part): part is { type: "text"; text: string } => Boolean(part && typeof part === "object" && (part as { type?: unknown }).type === "text" && typeof (part as { text?: unknown }).text === "string")).map((part) => part.text).join("");
    if (text.trim()) return text.trim();
  }
  return "没有收到可显示的研究答复。";
}

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
  let assistant: PiRpcClient | undefined;

  const close = async (): Promise<void> => {
    const current = server;
    server = undefined;
    workbenchUrl = undefined;
    const currentAssistant = assistant;
    assistant = undefined;
    await currentAssistant?.stop();
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
          const next = createPanelServer(ctx.cwd, { assistant: async (message) => {
            if (!assistant) {
              assistant = new PiRpcClient({
                cwd: ctx.cwd,
                ...(ctx.model?.provider === undefined ? {} : { provider: ctx.model.provider }),
                ...(ctx.model?.id === undefined ? {} : { model: ctx.model.id }),
                env: assistantEnv(ctx.model?.provider),
                tools: ["read", "grep", "find", "ls"],
              });
              try {
                await assistant.start();
              } catch (error) {
                await assistant.stop().catch(() => undefined);
                assistant = undefined;
                throw error;
              }
            }
            const current = assistant;
            const events = await current.promptAndWait([
              "You are the psyclaw browser research assistant.",
              "Work in a read-only mode. You may inspect project files with read, grep, find, and ls only.",
              "Do not claim a statistical result, citation, or completed action without evidence.",
              "When the user asks for a change or side effect, explain the proposed plan and state that approval is required.",
              `User request: ${message}`,
            ].join("\n"));
            return { text: assistantText(events as Array<Record<string, unknown>>) };
          }});
          const actualPort = await listen(next, 0);
          server = next;
          workbenchUrl = `http://127.0.0.1:${actualPort}`;
        }
        openWorkbench(workbenchUrl);
        ctx.ui.notify("科研工作台已在浏览器中打开", "info");
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
