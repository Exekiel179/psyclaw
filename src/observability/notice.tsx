import React, { useState } from "react";
import { Box, Text, render, useInput } from "ink";
import { PSYCLAW_ACCENT } from "../branding.js";
import {
  readTelemetryPreference,
  shouldShowTelemetryNotice,
  telemetryPreferenceOptions,
  writeTelemetryPreference,
  type TelemetryPreference,
} from "./preference.js";

export type TelemetryNoticeChoice = "continue" | "disable";

function TelemetryNotice({ onDone }: { onDone: (choice: TelemetryNoticeChoice) => void }): React.ReactElement {
  const [choice, setChoice] = useState<0 | 1>(0);

  useInput((input, key) => {
    if (key.upArrow || key.downArrow || key.leftArrow || key.rightArrow || input === "j" || input === "k") {
      setChoice((value) => (value === 0 ? 1 : 0));
      return;
    }
    if (input === "d" || input === "D") {
      onDone("disable");
      return;
    }
    if (key.return) onDone(choice === 0 ? "continue" : "disable");
  });

  return (
    <Box borderStyle="round" borderColor={PSYCLAW_ACCENT} paddingX={2} paddingY={1} flexDirection="column">
      <Text bold>匿名产品遥测默认开启</Text>
      <Text>PsyClaw 会发送匿名的产品使用与错误信息，用来改进工具本身。</Text>
      <Text dimColor>不含研究正文、论文、对话内容、个人路径或身份信息。随时可用 psyclaw telemetry off 关闭。</Text>
      <Box flexDirection="column" marginY={1}>
        <Text bold={choice === 0} color={choice === 0 ? PSYCLAW_ACCENT : "gray"}>
          {choice === 0 ? "❯" : " "} 知道了，继续使用
        </Text>
        <Text bold={choice === 1} color={choice === 1 ? PSYCLAW_ACCENT : "gray"}>
          {choice === 1 ? "❯" : " "} 关闭遥测
        </Text>
      </Box>
      <Text dimColor>[Enter] 确认  ·  [↑/↓] 选择  ·  [D] 关闭遥测</Text>
    </Box>
  );
}

export function promptTelemetryNotice(): Promise<TelemetryNoticeChoice> {
  return new Promise((resolve) => {
    let instance: ReturnType<typeof render>;
    instance = render(
      <TelemetryNotice
        onDone={(choice) => {
          instance.unmount();
          resolve(choice);
        }}
      />,
      { stdout: process.stdout, exitOnCtrlC: false },
    );
  });
}

export async function maybeShowTelemetryNotice(options: {
  env?: NodeJS.ProcessEnv;
  settingsPath?: string;
  interactive?: boolean;
  prompt?: () => Promise<TelemetryNoticeChoice>;
} = {}): Promise<TelemetryPreference> {
  const env = options.env ?? process.env;
  const preference = await readTelemetryPreference(telemetryPreferenceOptions(options.settingsPath));
  const interactive = options.interactive ?? Boolean(process.stdin.isTTY && process.stdout.isTTY);
  if (!shouldShowTelemetryNotice(preference, env, interactive)) return preference;
  const choice = await (options.prompt ?? promptTelemetryNotice)();
  return writeTelemetryPreference(
    {
      enabled: choice !== "disable",
      noticeAcknowledged: true,
    },
    telemetryPreferenceOptions(options.settingsPath),
  );
}
