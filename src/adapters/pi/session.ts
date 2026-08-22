import {
  createAgentSession,
  DefaultResourceLoader,
  getAgentDir,
  ModelRuntime,
  SessionManager,
  SettingsManager,
  type AgentSession,
  type AgentSessionEvent,
  type AgentSessionEventListener,
  type ResourceLoader,
} from "@earendil-works/pi-coding-agent";
import { join } from "node:path";
import type { ModelRef } from "./model.js";
import { PiModelGateway } from "./model.js";
import { createPiResourceLoader } from "./resources.js";

export interface PiSessionOptions {
  cwd: string;
  agentDir?: string;
  sessionPath?: string;
  persistent?: boolean;
  modelRuntime?: ModelRuntime;
  model?: ModelRef;
  tools?: readonly string[];
  noExtensions?: boolean;
  noSkills?: boolean;
  noContextFiles?: boolean;
  resourceLoader?: ResourceLoader;
}

export interface PiSessionHandle {
  readonly session: AgentSession;
  readonly resources: ResourceLoader;
  readonly modelRuntime: ModelRuntime;
  readonly cwd: string;
  prompt(text: string): Promise<void>;
  subscribe(listener: AgentSessionEventListener): () => void;
  dispose(): void;
}

function assertAbsolute(value: string, label: string): void {
  if (!/^([A-Za-z]:[\\/]|[\\/]{1,2})/.test(value)) throw new Error(`${label} must be an absolute path`);
}

/**
 * Thin Pi SDK adapter. Business code receives this stable port instead of
 * importing AgentSession internals throughout the research implementation.
 */
export async function openPiSession(options: PiSessionOptions): Promise<PiSessionHandle> {
  assertAbsolute(options.cwd, "cwd");
  const agentDir = options.agentDir ?? getAgentDir();
  assertAbsolute(agentDir, "agentDir");
  if (options.sessionPath !== undefined) assertAbsolute(options.sessionPath, "sessionPath");

  const modelRuntime = options.modelRuntime ?? await ModelRuntime.create({
    authPath: join(agentDir, "auth.json"),
    modelsPath: join(agentDir, "models.json"),
    allowModelNetwork: false,
    refreshOnCreate: false,
  });
  const resources = options.resourceLoader ?? await createPiResourceLoader({
    cwd: options.cwd,
    agentDir,
    ...(options.noExtensions === undefined ? {} : { noExtensions: options.noExtensions }),
    ...(options.noSkills === undefined ? {} : { noSkills: options.noSkills }),
    ...(options.noContextFiles === undefined ? {} : { noContextFiles: options.noContextFiles }),
  });
  const settingsManager = SettingsManager.inMemory({
    compaction: { enabled: true },
    retry: { enabled: true, maxRetries: 1 },
  });
  const sessionManager = options.sessionPath !== undefined
    ? SessionManager.open(options.sessionPath)
    : options.persistent
      ? SessionManager.create(options.cwd)
      : SessionManager.inMemory();
  const model = options.model === undefined
    ? undefined
    : new PiModelGateway(modelRuntime).resolve(options.model);
  const result = await createAgentSession({
    cwd: options.cwd,
    agentDir,
    modelRuntime,
    ...(model === undefined ? {} : { model }),
    tools: [...(options.tools ?? ["read", "grep", "find", "ls"])],
    resourceLoader: resources,
    sessionManager,
    settingsManager,
  });
  return {
    session: result.session,
    resources,
    modelRuntime,
    cwd: options.cwd,
    prompt: (text) => result.session.prompt(text),
    subscribe: (listener) => result.session.subscribe(listener),
    dispose: () => result.session.dispose(),
  };
}

export type PiSessionEvent = AgentSessionEvent;
