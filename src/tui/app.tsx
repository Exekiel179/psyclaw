import React, { useEffect, useState } from "react";
import { Box, Text, render, useApp, useInput } from "ink";
import { spawn } from "node:child_process";
import { discoverAgents, type AgentScan } from "../agents/discover.js";
import { importAgentSkills } from "../agents/import.js";
import { planAgentInstall, runInstall } from "../install/installer.js";
import { agentTableLines } from "./model.js";
import { PSYCLAW_ACCENT, PSYCLAW_ERROR, PSYCLAW_OK } from "../branding.js";

function spawnRunner(command: string): Promise<{ exitCode: number }> {
  const [bin, ...args] = command.split(/\s+/).filter(Boolean);
  return new Promise((resolve) => {
    const child = spawn(bin!, args, { stdio: "ignore", shell: false });
    child.on("error", () => resolve({ exitCode: 1 }));
    child.on("close", (code) => resolve({ exitCode: code ?? 1 }));
  });
}

type Mode = "browse" | "install-confirm" | "import-confirm" | "result";

function Banner(): React.ReactElement {
  return (
    <Box flexDirection="column" marginBottom={1}>
      <Box gap={1} alignItems="center">
        <Text color={PSYCLAW_ACCENT} bold>ψ PsyClaw shell</Text>
        <Text color="black" backgroundColor={PSYCLAW_ACCENT} bold> TUI </Text>
        <Text dimColor>智能体生态与技能管理 · 只读发现，显式授权</Text>
      </Box>
      <Text dimColor>──────────────────────────────────────────────────────────</Text>
    </Box>
  );
}

function Hint({ children }: { children: React.ReactNode }): React.ReactElement {
  return (
    <Box marginTop={1}>
      <Text dimColor>💡 {children}</Text>
    </Box>
  );
}

interface AppProps {
  root: string;
  homeDir?: string;
}

function App({ root, homeDir }: AppProps): React.ReactElement {
  const { exit } = useApp();
  const [scans, setScans] = useState<AgentScan[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(0);
  const [mode, setMode] = useState<Mode>("browse");
  const [message, setMessage] = useState<string[]>([]);
  const [resultOk, setResultOk] = useState(true);

  const refresh = async () => {
    setLoading(true);
    setScans(await discoverAgents({ ...(homeDir === undefined ? {} : { homeDir }) }));
    setLoading(false);
  };

  useEffect(() => {
    void refresh();
  }, []);

  const current = scans[selected];

  useInput(async (input, key) => {
    if (mode === "browse") {
      if (key.upArrow) setSelected((value) => Math.max(0, value - 1));
      if (key.downArrow) setSelected((value) => Math.min(Math.max(0, scans.length - 1), value + 1));
      if (input === "r") await refresh();
      if (input === "i" && current?.found) setMode("install-confirm");
      if (input === "m" && current?.found) setMode("import-confirm");
      if (input === "q") exit();
      return;
    }
    if (mode === "install-confirm" && current) {
      if (input === "y") {
        setMessage(["正在执行安装…"]);
        const receipt = await runInstall(
          planAgentInstall(current),
          { approved: true, actor: "researcher", reason: "tui" },
          spawnRunner,
        );
        setResultOk(receipt.ok);
        setMessage([`${receipt.ok ? "✔" : "✗"} ${current.name}: ${receipt.ok ? "已成功安装" : `安装失败 (${receipt.reasonCode ?? "unknown"})`}`]);
        setMode("result");
      }
      if (input === "n" || key.escape) setMode("browse");
      return;
    }
    if (mode === "import-confirm" && current) {
      if (input === "y") {
        const result = await importAgentSkills({
          root,
          agent: current,
          approval: { approved: true, actor: "researcher", reason: "tui" },
        });
        setResultOk(true);
        setMessage([`✔ 已从 ${current.name} 导入 ${result.importedCount} 个学术技能`, `产物清单: ${result.manifestPath}`]);
        setMode("result");
      }
      if (input === "n" || key.escape) setMode("browse");
      return;
    }
    if (mode === "result" && (input === "q" || key.escape)) {
      setMode("browse");
    }
  });

  const table = agentTableLines(scans);

  return (
    <Box borderStyle="round" borderColor={PSYCLAW_ACCENT} paddingX={2} paddingY={1} flexDirection="column">
      <Banner />
      <Box flexDirection="column" marginY={1}>
        {loading
          ? <Text dimColor>正在扫描本机已安装智能体…</Text>
          : table.map((line, index) => {
              if (index === 0) return <Text key="header" bold color={PSYCLAW_ACCENT}>{line}</Text>;
              if (index === 1) return <Text key="divider" dimColor>{line}</Text>;
              const isSelected = index === selected + 2;
              return (
                <Box key={`${index}:${line}`}>
                  <Text color={isSelected ? PSYCLAW_ACCENT : "gray"} bold={isSelected}>
                    {isSelected ? "❯ " : "  "}
                  </Text>
                  {isSelected ? (
                    <Text bold color={PSYCLAW_ACCENT}>{line}</Text>
                  ) : (
                    <Text>{line}</Text>
                  )}
                </Box>
              );
            })}
      </Box>
      <Box flexDirection="column">
        <Hint>[↑/↓] 选择 · [R] 刷新 · [I] 安装扩展 · [M] 导入技能 · [Q] 退出</Hint>
        {mode === "install-confirm" && current && (
          <Box marginTop={1} flexDirection="column">
            <Text color={PSYCLAW_ACCENT} bold>➜ 确认安装 {current.name}？(按 Y 确认，N 取消)</Text>
            <Text dimColor>执行命令: {current.install?.installCommand || "无自动化命令（需手动安装）"}</Text>
          </Box>
        )}
        {mode === "import-confirm" && current && (
          <Box marginTop={1} flexDirection="column">
            <Text color={PSYCLAW_ACCENT} bold>➜ 确认将 {current.name} 的 {current.skills.length} 个技能导入 .psyclaw/imports？(按 Y 确认，N 取消)</Text>
          </Box>
        )}
        {mode === "result" && (
          <Box marginTop={1} flexDirection="column">
            {message.map((line) => (
              <Text key={line} color={resultOk ? PSYCLAW_OK : PSYCLAW_ERROR} bold>{line}</Text>
            ))}
            <Text dimColor>[Q / Esc] 返回列表</Text>
          </Box>
        )}
      </Box>
    </Box>
  );
}

export function runTui(root: string, options: { homeDir?: string } = {}): void {
  render(
    <App root={root} {...(options.homeDir === undefined ? {} : { homeDir: options.homeDir })} />,
    { stdout: process.stdout, exitOnCtrlC: true },
  );
}
