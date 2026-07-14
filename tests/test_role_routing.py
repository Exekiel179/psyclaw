"""按角色模型路由(feat-114)—— 常驻 agent 可各自配置 provider/model。

规格:
- 配置键为扁平键 `<role>_provider` / `<role>_model` / `<role>_base_url`
  (与 config._parse_simple 的扁平解析一致),环境变量 PSYCLAW_<ROLE>_<KEY> 同样生效;
- 任一角色键存在 → 构建该角色专属 provider;都不存在 → 返回默认(不多建实例);
- 换 provider 时**不继承**全局 model/base_url(避免跨厂商张冠李戴),
  未指定项回落该 preset 默认值;
- run_review 的 reviewer 调用走 reviewer 路由 provider(集成点抽查)。

运行:python -m pytest tests/test_role_routing.py 或直接 python 本文件。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.providers import AGENT_ROLES, get_role_provider  # noqa: E402
from psyclaw.providers.mock import MockProvider  # noqa: E402


def _conf(**extra) -> dict:
    base = {"provider": "mock", "model": "default", "base_url": ""}
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# 常量与基本回落
# ---------------------------------------------------------------------------

def test_agent_roles_covers_resident_agents():
    for role in ("planner", "executor", "critic", "reviewer", "auditor", "writer"):
        assert role in AGENT_ROLES


def test_no_override_returns_default_instance():
    # 未配置任何角色键 → 原样返回 default,不重复建实例。
    sentinel = MockProvider(model="global")
    p = get_role_provider(_conf(), "critic", default=sentinel)
    assert p is sentinel


def test_no_override_without_default_builds_global():
    p = get_role_provider(_conf(), "critic")
    assert isinstance(p, MockProvider)


# ---------------------------------------------------------------------------
# 角色键覆盖
# ---------------------------------------------------------------------------

def test_role_model_only_overrides_model_keeps_provider():
    sentinel = MockProvider(model="global")
    p = get_role_provider(_conf(critic_model="critic-x"), "critic", default=sentinel)
    assert p is not sentinel
    assert isinstance(p, MockProvider) and p.model == "critic-x"


def test_role_provider_switch_uses_preset_defaults():
    # critic 换到 ollama:模型/端点回落 ollama preset,不继承全局 base_url。
    conf = _conf(base_url="http://global:9999", critic_provider="ollama")
    p = get_role_provider(conf, "critic", default=MockProvider(model="global"))
    assert p.name != "mock"
    assert p.model == "qwen3:8b"                      # preset 默认模型
    assert "localhost:11434" in getattr(p, "base_url", "")   # 不继承全局端点


def test_role_provider_with_role_model_and_base_url():
    conf = _conf(reviewer_provider="ollama", reviewer_model="rev-14b",
                 reviewer_base_url="http://gpu-box:11434")
    p = get_role_provider(conf, "reviewer")
    assert p.model == "rev-14b"
    assert "gpu-box" in getattr(p, "base_url", "")


def test_roles_are_independent():
    conf = _conf(critic_model="critic-x")
    default = MockProvider(model="global")
    assert get_role_provider(conf, "planner", default=default) is default
    assert get_role_provider(conf, "critic", default=default).model == "critic-x"


# ---------------------------------------------------------------------------
# 配置层:环境变量 PSYCLAW_<ROLE>_<KEY>
# ---------------------------------------------------------------------------

def test_load_config_picks_role_env(monkeypatch, tmp_path):
    from psyclaw import config as cfg
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr(cfg, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setenv("PSYCLAW_CRITIC_MODEL", "env-critic")
    monkeypatch.setenv("PSYCLAW_REVIEWER_PROVIDER", "ollama")
    conf = cfg.load_config()
    assert conf["critic_model"] == "env-critic"
    assert conf["reviewer_provider"] == "ollama"


# ---------------------------------------------------------------------------
# 集成点抽查:run_review 的 reviewer 调用走 reviewer 路由
# ---------------------------------------------------------------------------

_PANEL = """\
### R1 方法学
RECOMMENDATION: ACCEPT

### R2 理论
RECOMMENDATION: ACCEPT

### R3 可复现性
RECOMMENDATION: ACCEPT

## REQUIRED REVISIONS
"""


class _CountingProvider:
    def __init__(self, model):
        self.name, self.model, self.n_calls = "seq", model, 0

    def chat(self, messages, system=""):
        self.n_calls += 1
        yield _PANEL


def test_run_review_routes_reviewer_provider(monkeypatch):
    import psyclaw.providers as prov
    from psyclaw import config as cfg
    from psyclaw.review import run_review

    built: dict[str, _CountingProvider] = {}

    def fake_get_provider(conf):
        p = _CountingProvider(conf.get("model") or "default")
        built[p.model] = p
        return p

    monkeypatch.setattr(prov, "get_provider", fake_get_provider)
    monkeypatch.setattr(cfg, "load_config", lambda: _conf(reviewer_model="rev-x"))

    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        draft = proj / "draft.md"
        draft.write_text("# 稿件\n效应量 d=0.5, 95% CI [0.2, 0.8]。", encoding="utf-8")
        rc = run_review(draft=str(draft), project_dir=str(proj))
        assert rc == 0
        # reviewer 的评审调用必须打在 rev-x 上,全局 provider 零调用。
        assert built["rev-x"].n_calls == 1
        assert built.get("default") is None or built["default"].n_calls == 0
        data = json.loads((proj / "notes" / "review_panel.json")
                          .read_text(encoding="utf-8"))
        assert data["decision"] == "ACCEPT"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
