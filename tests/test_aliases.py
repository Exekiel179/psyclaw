"""用户自定义命令别名测试(v0.2)—— 解析/合并/展开/内置优先/fail-safe。"""

from __future__ import annotations

from psyclaw.aliases import expand_alias, load_aliases


def _write(tmp_path, scope_dir, body):
    d = scope_dir / ".psyclaw"
    d.mkdir(parents=True, exist_ok=True)
    (d / "aliases.yaml").write_text(body, encoding="utf-8")


def test_load_and_expand(tmp_path):
    _write(tmp_path, tmp_path, "qc: check --journal xinlixuebao\n起跑: auto-loop --auto\n")
    aliases = load_aliases(str(tmp_path))
    assert aliases["qc"] == "check --journal xinlixuebao"
    out = expand_alias(["qc", "draft.md"], aliases)
    assert out == ["check", "--journal", "xinlixuebao", "draft.md"]   # 余参追加
    assert expand_alias(["起跑"], aliases) == ["auto-loop", "--auto"]


def test_builtin_wins_over_alias(tmp_path):
    aliases = {"check": "rm -rf /", "status": "auto-loop"}
    assert expand_alias(["check", "d.md"], aliases,
                        builtin={"check", "status"}) == ["check", "d.md"]   # 不劫持内置


def test_no_alias_passthrough():
    assert expand_alias(["status"], {}) == ["status"]
    assert expand_alias([], {"a": "b"}) == []
    assert expand_alias(["--help"], {"--help": "x"}) == ["--help"]


def test_quoted_args_and_comments(tmp_path):
    _write(tmp_path, tmp_path, "# 注释\n综述: lit-loop \"正念 与 焦虑\" --skip-gates\n\n")
    out = expand_alias(["综述"], load_aliases(str(tmp_path)))
    assert out == ["lit-loop", "正念 与 焦虑", "--skip-gates"]


def test_bad_file_fail_safe(tmp_path):
    d = tmp_path / ".psyclaw"
    d.mkdir()
    (d / "aliases.yaml").write_bytes(b"\xff\xfe bad")
    assert isinstance(load_aliases(str(tmp_path)), dict)   # 不抛异常


def test_bad_alias_value_fail_safe():
    # 引号不闭合 → shlex 抛 ValueError → 原样返回
    assert expand_alias(["x"], {"x": 'check "unclosed'}) == ["x"]
