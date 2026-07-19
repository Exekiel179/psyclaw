"""嵌入外部审稿 skill:nature-review 内置提炼版 + 通用 skill install 装全量。"""
from __future__ import annotations

from psyclaw.skills.install import install_skill_repo, repo_name


def test_repo_name():
    assert repo_name("https://github.com/mumdark/nature-review-studio") == "nature-review-studio"
    assert repo_name("https://github.com/x/y.git/") == "y"


def test_install_clones_ok(tmp_path):
    calls = {}

    class _R:
        returncode = 0
        stderr = ""
    def _runner(cmd, **k):
        calls["cmd"] = cmd
        (tmp_path / "nature-review-studio").mkdir(parents=True, exist_ok=True)
        return _R()
    r = install_skill_repo("https://github.com/mumdark/nature-review-studio",
                           dest_dir=str(tmp_path), mirror=False, runner=_runner)
    assert r["ok"] is True
    assert calls["cmd"][:2] == ["git", "clone"]


def test_install_rejects_non_https_argv_injection(tmp_path):
    # 安全:非 https(含 --flag 走私 / ext:: 危险协议)必须拒绝,不进 git clone
    ran = {"called": False}

    def _runner(*a, **k):
        ran["called"] = True
        return None
    for bad in ("--upload-pack=touch /tmp/x", "ext::sh -c id",
                "file:///etc", "git@github.com:x/y", "-oProxyCommand=x"):
        r = install_skill_repo(bad, dest_dir=str(tmp_path), runner=_runner)
        assert r["ok"] is False and "https" in r["note"]
    assert ran["called"] is False              # 危险 url 从不触达 git


def test_install_uses_end_of_options_sentinel(tmp_path):
    seen = {}

    class _R:
        returncode = 0
        stderr = ""
    def _runner(cmd, **k):
        seen["cmd"] = cmd
        (tmp_path / "y").mkdir(parents=True, exist_ok=True)
        return _R()
    install_skill_repo("https://github.com/x/y", dest_dir=str(tmp_path),
                       mirror=False, runner=_runner)
    assert "--" in seen["cmd"]                  # end-of-options 哨兵
    assert seen["cmd"].index("--") < seen["cmd"].index("https://github.com/x/y")


def test_install_clone_failure_gives_manual(tmp_path):
    class _R:
        returncode = 1
        stderr = "fatal: could not read"
    r = install_skill_repo("https://github.com/x/y", dest_dir=str(tmp_path),
                           mirror=False, runner=lambda *a, **k: _R())
    assert r["ok"] is False and "手动:git clone" in r["note"]


def test_install_no_git_failsafe(tmp_path):
    def _boom(*a, **k):
        raise FileNotFoundError("git")
    r = install_skill_repo("https://github.com/x/y", dest_dir=str(tmp_path),
                           mirror=False, runner=_boom)
    assert r["ok"] is False and "未装 git" in r["note"]


def test_install_already_present(tmp_path):
    (tmp_path / "y" ).mkdir()
    (tmp_path / "y" / "SKILL.md").write_text("x", encoding="utf-8")
    r = install_skill_repo("https://github.com/x/y", dest_dir=str(tmp_path),
                           runner=lambda *a, **k: None)
    assert r["ok"] is True and "已安装" in r["note"]


def test_nature_review_skill_discovered():
    from psyclaw.skills.loader import list_skills
    names = {s["name"] for s in list_skills(".", include_external=False)}
    assert "nature-review" in names


def test_nature_review_in_system_prompt_catalog():
    from psyclaw.context import skills_catalog
    cat = skills_catalog(".")
    assert "nature-review" in cat
