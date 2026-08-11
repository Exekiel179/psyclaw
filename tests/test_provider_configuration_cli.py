"""无模型配置时 CLI 的显式失败契约。"""

from __future__ import annotations

from psyclaw import cli


def test_main_reports_provider_configuration_error(monkeypatch, capsys):
    monkeypatch.setattr(cli.cfg, "load_config", lambda: {})

    rc = cli.main(["agent", "检查项目状态"])

    assert rc == 2
    output = capsys.readouterr().out
    assert "未配置 LLM provider" in output
    assert "psyclaw config" in output
