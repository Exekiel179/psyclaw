"""psyclaw update 自更新:形态自适应 + 国内镜像。"""
from __future__ import annotations

from pathlib import Path

from psyclaw import update as up


def test_detect_source_in_git_worktree(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "psyclaw").mkdir()
    kind, repo = up.detect_install_kind(pkg_dir=tmp_path / "psyclaw", executable="/usr/bin/python")
    assert kind == "source" and repo == str(tmp_path)


def test_detect_uv_tool(tmp_path):
    kind, repo = up.detect_install_kind(
        pkg_dir=tmp_path, executable="/Users/x/.local/share/uv/tools/psyclaw/bin/python")
    assert kind == "uv-tool" and repo is None


def test_detect_pip_default(tmp_path):
    kind, repo = up.detect_install_kind(pkg_dir=tmp_path, executable="/usr/bin/python3")
    assert kind == "pip"


def test_upgrade_command_source_pulls():
    cmd = up.upgrade_command("source", repo_dir="/x/psyclaw")
    assert cmd[:3] == ["git", "-C", "/x/psyclaw"] and "pull" in cmd


def test_upgrade_command_uvtool_reinstalls():
    cmd = up.upgrade_command("uv-tool")
    assert cmd[:3] == ["uv", "tool", "install"] and "--force" in cmd
    assert any("git+https://github.com/" in c for c in cmd)


def test_upgrade_command_mirror_uses_gitclone():
    cmd = up.upgrade_command("uv-tool", mirror=True)
    assert any("gitclone.com" in c for c in cmd)


def test_upgrade_command_pip():
    cmd = up.upgrade_command("pip")
    assert cmd[-4:-1] == ["-m", "pip", "install"] or ("pip" in cmd and "install" in cmd)
    assert "-U" in cmd


def test_env_for_mirror_sets_aliyun():
    e = up.env_for(True)
    assert "aliyun" in e["UV_DEFAULT_INDEX"] and "aliyun" in e["PIP_INDEX_URL"]
    assert "UV_DEFAULT_INDEX" not in up.env_for(False)


def test_should_mirror_auto_when_github_unreachable():
    assert up.should_mirror(explicit=None, reachable_fn=lambda: False) is True
    assert up.should_mirror(explicit=None, reachable_fn=lambda: True) is False
    assert up.should_mirror(explicit=True, reachable_fn=lambda: True) is True   # 显式优先


def test_run_update_injected_runner_ok():
    class _R:
        returncode = 0
        stdout = "Updated"
        stderr = ""
    out = up.run_update("uv-tool", runner=lambda *a, **k: _R())
    assert out["ok"] is True and "Updated" in out["out"]


def test_run_update_never_raises():
    def _boom(*a, **k):
        raise RuntimeError("no network")
    out = up.run_update("pip", runner=_boom)
    assert out["ok"] is False and "失败" in out["out"]
