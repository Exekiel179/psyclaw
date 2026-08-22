import React, { useState } from "react";
import { Box, Text, render, useInput } from "ink";
import { PROVIDER_PRESETS, setupProviders } from "./setup.js";
import { PSYCLAW_ACCENT, PSYCLAW_ERROR, PSYCLAW_OK } from "./branding.js";

export type WizardStep = "welcome" | "provider" | "model" | "confirm" | "done";

export interface WizardResult {
  completed: boolean;
  provider?: string;
  modelId?: string;
}

function Banner(): React.ReactElement {
  return (
    <Box flexDirection="column" marginBottom={1}>
      <Box gap={1} alignItems="center">
        <Text color={PSYCLAW_ACCENT} bold>ψ PsyClaw</Text>
        <Text color="black" backgroundColor={PSYCLAW_ACCENT} bold> v0.24.0 </Text>
        <Text dimColor>社科科研智能体 · 首次配置向导</Text>
      </Box>
      <Text dimColor>──────────────────────────────────────────────────</Text>
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

function Selectable({ lines, selected }: { lines: readonly string[]; selected: number }): React.ReactElement {
  return (
    <Box flexDirection="column" marginY={1}>
      {lines.map((line, index) => {
        const isSelected = index === selected;
        return (
          <Box key={line} gap={1}>
            <Text color={isSelected ? PSYCLAW_ACCENT : "gray"} bold={isSelected}>
              {isSelected ? "❯" : " "}
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
  );
}

interface WizardProps {
  onDone: (result: WizardResult) => void;
}

function Wizard({ onDone }: WizardProps): React.ReactElement {
  const [step, setStep] = useState<WizardStep>("welcome");
  const [providerIndex, setProviderIndex] = useState(0);
  const [modelIndex, setModelIndex] = useState(0);

  const provider = PROVIDER_PRESETS[providerIndex];
  const model = provider?.models[modelIndex];
  const apiKeyEnv = provider?.apiKeyEnv ?? "";
  const keyConfigured = process.env[apiKeyEnv] !== undefined && process.env[apiKeyEnv] !== "";

  const writeConfig = async () => {
    if (!provider) return;
    await setupProviders({ providers: [provider.id] });
    setStep("done");
  };

  useInput((input, key) => {
    if (input === "q" && step !== "done") {
      onDone({ completed: false });
      return;
    }
    switch (step) {
      case "welcome":
        if (key.return) setStep("provider");
        break;
      case "provider":
        if (key.upArrow) setProviderIndex((value) => Math.max(0, value - 1));
        if (key.downArrow) setProviderIndex((value) => Math.min(PROVIDER_PRESETS.length - 1, value + 1));
        if (key.return) {
          setModelIndex(0);
          setStep("model");
        }
        break;
      case "model":
        if (key.upArrow) setModelIndex((value) => Math.max(0, value - 1));
        if (key.downArrow) setModelIndex((value) => Math.min((provider?.models.length ?? 1) - 1, value + 1));
        if (key.return) setStep("confirm");
        break;
      case "confirm":
        if (key.return) void writeConfig();
        if (key.escape) setStep("provider");
        break;
      case "done":
        if (key.return || input === "q") {
          onDone({
            completed: true,
            ...(provider?.id === undefined ? {} : { provider: provider.id }),
            ...(model?.id === undefined ? {} : { modelId: model.id }),
          });
        }
        break;
    }
  });

  const providerLines = PROVIDER_PRESETS.map((preset) => `${preset.name.padEnd(20)} (环境变量: $${preset.apiKeyEnv})`);
  const modelLines = provider ? provider.models.map((entry) => `${entry.name.padEnd(26)} [${entry.id}]`) : [];

  return (
    <Box borderStyle="round" borderColor={PSYCLAW_ACCENT} paddingX={2} paddingY={1} flexDirection="column">
      <Banner />

      {step === "welcome" && (
        <Box flexDirection="column">
          <Text bold>欢迎使用 PsyClaw！</Text>
          <Text dimColor>首次运行需配置一个模型提供商（API Key 由本地环境变量安全管理，绝不上报）。</Text>
          <Hint>[Enter] 开始配置  ·  [Q] 退出</Hint>
        </Box>
      )}

      {step === "provider" && (
        <Box flexDirection="column">
          <Text bold color={PSYCLAW_ACCENT}>[1/3] 选择模型提供商 (Provider)</Text>
          <Selectable lines={providerLines} selected={providerIndex} />
          <Hint>[↑/↓] 移动光标  ·  [Enter] 确认选择  ·  [Q] 退出</Hint>
        </Box>
      )}

      {step === "model" && (
        <Box flexDirection="column">
          <Text bold color={PSYCLAW_ACCENT}>[2/3] 选择默认模型 ({provider?.name})</Text>
          <Selectable lines={modelLines} selected={modelIndex} />
          <Hint>[↑/↓] 移动光标  ·  [Enter] 确认选择  ·  [Q] 退出</Hint>
        </Box>
      )}

      {step === "confirm" && (
        <Box flexDirection="column">
          <Text bold color={PSYCLAW_ACCENT}>[3/3] 确认配置并写入</Text>
          <Box flexDirection="column" marginY={1}>
            <Text>• 提供商: <Text color={PSYCLAW_ACCENT} bold>{provider?.name}</Text></Text>
            <Text>• 模  型: <Text color={PSYCLAW_ACCENT} bold>{model?.name}</Text> <Text dimColor>({model?.id})</Text></Text>
            <Text color={keyConfigured ? PSYCLAW_OK : PSYCLAW_ERROR} bold>
              • API Key: {keyConfigured ? `✔ 已就绪 ($${apiKeyEnv})` : `✗ 未检测到 $${apiKeyEnv}（请先在环境设置）`}
            </Text>
          </Box>
          <Hint>[Enter] 保存并启动对话  ·  [Esc] 返回上一步  ·  [Q] 退出</Hint>
        </Box>
      )}

      {step === "done" && (
        <Box flexDirection="column">
          <Text color={PSYCLAW_OK} bold>✔ 配置已成功写入 models.json 与环境缓存！</Text>
          <Text dimColor>马上启动 PsyClaw 智能研究助手…</Text>
          <Hint>[Enter] 立即进入对话  ·  [Q] 退出</Hint>
        </Box>
      )}
    </Box>
  );
}

export function runWizard(): Promise<WizardResult> {
  return new Promise((resolve) => {
    let instance: ReturnType<typeof render>;
    instance = render(
      <Wizard onDone={(result) => {
        instance.unmount();
        resolve(result);
      }} />,
      { stdout: process.stdout, exitOnCtrlC: false },
    );
  });
}
