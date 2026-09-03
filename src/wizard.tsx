import React, { useEffect, useState } from "react";
import { Box, Text, render, useInput } from "ink";
import { PROVIDER_PRESETS, providerCredentialSource, readMacOsLoginShellCredential, saveProviderConfig } from "./setup.js";
import { PSYCLAW_ACCENT, PSYCLAW_ERROR, PSYCLAW_OK, PSYCLAW_VERSION } from "./branding.js";

export type WizardStep = "welcome" | "provider" | "model" | "credential" | "confirm" | "done";

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
        <Text color="black" backgroundColor={PSYCLAW_ACCENT} bold> v{PSYCLAW_VERSION} </Text>
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
  const maxVisible = 8;
  const start = Math.min(
    Math.max(0, selected - Math.floor(maxVisible / 2)),
    Math.max(0, lines.length - maxVisible),
  );
  const visible = lines.slice(start, start + maxVisible);
  return (
    <Box flexDirection="column" marginY={1}>
      {visible.map((line, offset) => {
        const index = start + offset;
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
      {lines.length > maxVisible && <Text dimColor>第 {selected + 1}/{lines.length} 项</Text>}
    </Box>
  );
}

interface WizardProps {
  onDone: (result: WizardResult) => void;
}

function Wizard({ onDone }: WizardProps): React.ReactElement {
  const wizardProviders = PROVIDER_PRESETS.filter((preset) => preset.models.length > 0);
  const [step, setStep] = useState<WizardStep>("welcome");
  const [providerIndex, setProviderIndex] = useState(0);
  const [modelIndex, setModelIndex] = useState(0);
  const [apiKey, setApiKey] = useState("");
  const [credentialSource, setCredentialSource] = useState<string>("checking");
  const [credentialError, setCredentialError] = useState("");
  const [saving, setSaving] = useState(false);

  const provider = wizardProviders[providerIndex];
  const model = provider?.models[modelIndex];
  const apiKeyEnv = provider?.apiKeyEnv ?? "";
  const keyConfigured = credentialSource !== "missing" && credentialSource !== "checking";

  useEffect(() => {
    let active = true;
    setCredentialSource("checking");
    if (provider) void providerCredentialSource(provider)
      .then((source) => { if (active) setCredentialSource(source); })
      .catch(() => { if (active) setCredentialSource("missing"); });
    return () => { active = false; };
  }, [provider]);

  useEffect(() => {
    setApiKey("");
  }, [providerIndex]);

  const writeConfig = async () => {
    if (!provider || saving) return;
    setSaving(true);
    setCredentialError("");
    try {
      await saveProviderConfig({ ...provider, ...(apiKey.trim() ? { apiKey: apiKey.trim() } : {}) });
      setStep("done");
    } catch (error) {
      setCredentialError(error instanceof Error ? error.message : "Provider 配置保存失败");
    } finally {
      setSaving(false);
    }
  };

  useInput((input, key) => {
    if (input === "q" && step !== "done" && step !== "credential") {
      onDone({ completed: false });
      return;
    }
    switch (step) {
      case "welcome":
        if (key.return) setStep("provider");
        break;
      case "provider":
        if (key.upArrow) setProviderIndex((value) => Math.max(0, value - 1));
        if (key.downArrow) setProviderIndex((value) => Math.min(wizardProviders.length - 1, value + 1));
        if (key.return) {
          setModelIndex(0);
          setStep("model");
        }
        break;
      case "model":
        if (key.upArrow) setModelIndex((value) => Math.max(0, value - 1));
        if (key.downArrow) setModelIndex((value) => Math.min((provider?.models.length ?? 1) - 1, value + 1));
        if (key.return) setStep("credential");
        break;
      case "credential":
        if (key.escape) setStep("model");
        else if (key.return && (keyConfigured || apiKey.trim())) setStep("confirm");
        else if (key.ctrl && input.toLowerCase() === "i" && process.platform === "darwin") {
          setCredentialError("");
          void readMacOsLoginShellCredential(apiKeyEnv)
            .then((value) => value ? setApiKey(value) : setCredentialError(`登录 shell 中未找到 ${apiKeyEnv}`))
            .catch((error: unknown) => setCredentialError(error instanceof Error ? error.message : "登录 shell 导入失败"));
        }
        else if (key.backspace || key.delete) setApiKey((value) => value.slice(0, -1));
        else if (input && !key.ctrl && !key.meta) setApiKey((value) => value + input.replace(/[\r\n]/g, ""));
        break;
      case "confirm":
        if (key.return && !saving) void writeConfig();
        if (key.escape && !saving) setStep("provider");
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

  const providerLines = wizardProviders.map((preset) => `${preset.name.padEnd(20)} (环境变量: $${preset.apiKeyEnv})`);
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
          <Text bold color={PSYCLAW_ACCENT}>[1/4] 选择模型提供商 (Provider)</Text>
          <Selectable lines={providerLines} selected={providerIndex} />
          <Hint>[↑/↓] 移动光标  ·  [Enter] 确认选择  ·  [Q] 退出</Hint>
        </Box>
      )}

      {step === "model" && (
        <Box flexDirection="column">
          <Text bold color={PSYCLAW_ACCENT}>[2/4] 选择默认模型 ({provider?.name})</Text>
          <Selectable lines={modelLines} selected={modelIndex} />
          <Hint>[↑/↓] 移动光标  ·  [Enter] 确认选择  ·  [Q] 退出</Hint>
        </Box>
      )}

      {step === "confirm" && (
        <Box flexDirection="column">
          <Text bold color={PSYCLAW_ACCENT}>[4/4] 确认配置并写入</Text>
          <Box flexDirection="column" marginY={1}>
            <Text>• 提供商: <Text color={PSYCLAW_ACCENT} bold>{provider?.name}</Text></Text>
            <Text>• 模  型: <Text color={PSYCLAW_ACCENT} bold>{model?.name}</Text> <Text dimColor>({model?.id})</Text></Text>
            <Text color={keyConfigured || apiKey.trim() ? PSYCLAW_OK : PSYCLAW_ERROR} bold>
              • API Key: {apiKey.trim() ? "✔ 将保存到用户级凭据文件 auth.json" : `✔ 已检测到 (${credentialSource})`}
            </Text>
          </Box>
          {credentialError && <Text color={PSYCLAW_ERROR}>{credentialError}</Text>}
          <Hint>{saving ? "正在保存配置…" : "[Enter] 保存并启动对话  ·  [Esc] 返回上一步  ·  [Q] 退出"}</Hint>
        </Box>
      )}

      {step === "credential" && (
        <Box flexDirection="column">
          <Text bold color={PSYCLAW_ACCENT}>[3/4] 配置 API Key</Text>
          <Text dimColor>已检查当前进程、macOS launchctl 与用户凭据存储。</Text>
          <Box marginY={1}><Text>Key: </Text><Text color={PSYCLAW_ACCENT}>{apiKey ? "•".repeat(Math.min(apiKey.length, 48)) : keyConfigured ? "已检测到，可直接继续" : "请输入 API Key"}</Text></Box>
          {!keyConfigured && !apiKey.trim() && <Text color={PSYCLAW_ERROR}>未检测到 ${apiKeyEnv}</Text>}
          {credentialError && <Text color={PSYCLAW_ERROR}>{credentialError}</Text>}
          <Hint>直接输入 Key（内容不回显）{process.platform === "darwin" ? " · [Ctrl+I] 明确从 login shell 导入并保存" : ""} · [Enter] 继续 · [Esc] 返回</Hint>
        </Box>
      )}

      {step === "done" && (
        <Box flexDirection="column">
          <Text color={PSYCLAW_OK} bold>✔ Provider 与凭据配置已保存！</Text>
          <Text dimColor>马上启动 PsyClaw 智能研究助手…</Text>
          <Hint>[Enter] 立即进入对话  ·  [Q] 退出</Hint>
        </Box>
      )}
    </Box>
  );
}

export async function runWizard(): Promise<WizardResult> {
  let finish: ((result: WizardResult) => void) | undefined;
  const resultPromise = new Promise<WizardResult>((resolve) => {
    finish = resolve;
  });
  let completed = false;
  const instance = render(
    <Wizard onDone={(result) => {
      if (completed) return;
      completed = true;
      finish?.(result);
      instance.unmount();
    }} />,
    { stdout: process.stdout, exitOnCtrlC: false },
  );

  const result = await resultPromise;
  // Do not start Pi until Ink has restored raw mode and released stdin.
  await instance.waitUntilExit();
  return result;
}
