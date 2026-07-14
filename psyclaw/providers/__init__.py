"""Provider 工厂与预设注册表(模型名均经官方文档核实,2026-06)。

  anthropic  Claude         claude-sonnet-4-6 / claude-opus-4-8 / claude-fable-5
  openai     OpenAI         gpt-5.5 / gpt-5.5-pro
  deepseek   DeepSeek       deepseek-v4-flash / deepseek-v4-pro
                            (deepseek-chat/reasoner 2026-07-24 弃用)
  qwen       通义千问       qwen3.6-plus / qwen3.7-max / qwen3.6-flash
  zhipu      智谱 GLM       glm-5 / glm-5.1 / glm-5-turbo
  moonshot   Kimi           kimi-k2.6 / kimi-k2.5(可用 /v1/models 查账号可见模型)
  ollama     本地           qwen3:8b 等,免 key
  lmstudio   本地           免 key
  opencode   OpenCode(Go)   驱动本地 opencode CLI,模型由 opencode 自己配置
  custom     任意 OpenAI 兼容端点(中转站)
  mock       离线回显
"""

from __future__ import annotations

from psyclaw.providers.base import Provider
from psyclaw.providers.mock import MockProvider

PRESETS: dict = {
    "anthropic": {"label": "Anthropic Claude(官方/中转)", "protocol": "anthropic",
                  "base_url": "https://api.anthropic.com",
                  "model": "claude-sonnet-4-6",
                  "models": ["claude-sonnet-4-6", "claude-opus-4-8", "claude-fable-5"],
                  "key_env": "ANTHROPIC_API_KEY"},
    "openai":    {"label": "OpenAI(官方/中转)", "protocol": "openai",
                  "base_url": "https://api.openai.com",
                  "model": "gpt-5.5",
                  "models": ["gpt-5.5", "gpt-5.5-pro"],
                  "key_env": "OPENAI_API_KEY"},
    "deepseek":  {"label": "DeepSeek 深度求索", "protocol": "openai",
                  "base_url": "https://api.deepseek.com",
                  "model": "deepseek-v4-flash",
                  "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
                  "key_env": "DEEPSEEK_API_KEY"},
    "qwen":      {"label": "通义千问(阿里云百炼)", "protocol": "openai",
                  "base_url": "https://dashscope.aliyuncs.com/compatible-mode",
                  "model": "qwen3.6-plus",
                  "models": ["qwen3.6-plus", "qwen3.7-max", "qwen3.6-flash"],
                  "key_env": "DASHSCOPE_API_KEY"},
    "zhipu":     {"label": "智谱 GLM", "protocol": "openai",
                  "base_url": "https://open.bigmodel.cn/api/paas/v4",
                  "model": "glm-5",
                  "models": ["glm-5", "glm-5.1", "glm-5-turbo"],
                  "key_env": "ZHIPU_API_KEY"},
    "moonshot":  {"label": "月之暗面 Kimi", "protocol": "openai",
                  "base_url": "https://api.moonshot.cn",
                  "model": "kimi-k2.6",
                  "models": ["kimi-k2.6", "kimi-k2.5"],
                  "key_env": "MOONSHOT_API_KEY"},
    "ollama":    {"label": "Ollama 本地模型(免 key)", "protocol": "openai",
                  "base_url": "http://localhost:11434",
                  "model": "qwen3:8b",
                  "models": ["qwen3:8b", "qwen3:14b", "deepseek-r1:8b", "llama3.1:8b"],
                  "key_env": None},
    "lmstudio":  {"label": "LM Studio 本地模型(免 key)", "protocol": "openai",
                  "base_url": "http://localhost:1234",
                  "model": "local-model", "models": [],
                  "key_env": None},
    "opencode":  {"label": "OpenCode CLI(Go,本地 agent 后端)", "protocol": "opencode",
                  "base_url": "", "model": "opencode-default", "models": [],
                  "key_env": None},
    "custom":    {"label": "自定义 OpenAI 兼容端点(中转站等)", "protocol": "openai",
                  "base_url": "", "model": "", "models": [],
                  "key_env": "OPENAI_API_KEY"},
    "mock":      {"label": "Mock 离线回显", "protocol": "mock",
                  "base_url": "", "model": "mock", "models": [],
                  "key_env": None},
}


# 常驻 agent 角色(feat-114:可按角色配置 <role>_provider/_model/_base_url)。
AGENT_ROLES = ("planner", "executor", "critic", "reviewer", "auditor", "writer")


def get_role_provider(conf: dict, role: str, default: Provider | None = None) -> Provider:
    """按常驻角色解析 provider(feat-114 按角色模型路由)。

    配置键为扁平键(与 config._parse_simple 一致):
      <role>_provider / <role>_model / <role>_base_url
    任一存在 → 构建该角色专属 provider;都不存在 → 返回 default(或全局)。
    换 provider 时不继承全局 model/base_url(跨厂商张冠李戴是硬错误),
    未指定项回落该 preset 的默认值。
    """
    role = (role or "").lower()
    r_provider = str(conf.get(f"{role}_provider") or "").strip()
    r_model = str(conf.get(f"{role}_model") or "").strip()
    r_base = str(conf.get(f"{role}_base_url") or "").strip()
    if not (r_provider or r_model or r_base):
        return default if default is not None else get_provider(conf)
    sub = dict(conf)
    if r_provider:
        sub["provider"] = r_provider
        sub["model"] = r_model      # 空 → get_provider 回落 preset 默认模型
        sub["base_url"] = r_base    # 空 → preset 默认端点
    else:
        if r_model:
            sub["model"] = r_model
        if r_base:
            sub["base_url"] = r_base
    return get_provider(sub)


def get_provider(conf: dict) -> Provider:
    name = (conf.get("provider") or "mock").lower()
    preset = PRESETS.get(name, PRESETS["custom"])
    model = conf.get("model") or ""
    if not model or model == "default":
        model = preset["model"] or "default"
    base_url = conf.get("base_url") or preset["base_url"]

    if preset["protocol"] == "mock":
        return MockProvider(model=model)

    if preset["protocol"] == "opencode":
        from psyclaw.providers.opencode_cli import OpenCodeProvider
        p = OpenCodeProvider(model=model)
        if p.available():
            return p
        print("[provider] 未找到 opencode CLI(npm i -g opencode-ai 或 go install),回落 mock。")
        return MockProvider(model=model)

    if preset["protocol"] == "anthropic":
        from psyclaw.providers.anthropic_api import AnthropicProvider
        p = AnthropicProvider(model=model, base_url=base_url)
        if p.api_key:
            return p
        print(f"[provider] 未找到 {preset['key_env']},回落 mock。运行 `psyclaw config`。")
        return MockProvider(model=model)

    from psyclaw.providers.openai_compat import OpenAICompatProvider
    p = OpenAICompatProvider(model=model, base_url=base_url,
                             key_env=preset["key_env"], display=name)
    if p.api_key or preset["key_env"] is None:
        return p
    print(f"[provider] 未找到 {preset['key_env']},回落 mock。运行 `psyclaw config`。")
    return MockProvider(model=model)
