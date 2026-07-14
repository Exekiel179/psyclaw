"""feat-125:沙箱核 + 策略模型(docs/SANDBOX.md)——单一裁决入口 + 审计 + fail-closed。"""

from __future__ import annotations

import json

from psyclaw import sandbox as SB


def test_disabled_allows_and_audits(tmp_path):
    r = SB.sandbox_check("exec", "run", {"code": "rm -rf /"}, str(tmp_path))
    assert r["allow"] is True and "未启用" in r["reason"]   # 未启用不新增限制


def _enable(tmp_path, **overrides):
    pol = {k: (dict(v) if isinstance(v, dict) else v)
           for k, v in SB.DEFAULT_POLICY.items()}
    pol["enabled"] = True
    pol.update(overrides)
    SB.save_policy(pol, str(tmp_path))


def test_exec_deny_pattern_fast_fail(tmp_path):
    _enable(tmp_path)
    r = SB.sandbox_check("exec", "run", {"code": "os.system('rm -rf /tmp/x')"},
                         str(tmp_path))
    assert r["allow"] is False and "恶意模式" in r["reason"]


def test_exec_normal_science_code_passes(tmp_path):
    _enable(tmp_path)
    r = SB.sandbox_check("exec", "run",
                         {"code": "import pandas as pd; pd.read_csv('data.csv')"},
                         str(tmp_path))
    assert r["allow"] is True                              # 正常科研代码不打断


def test_unknown_face_denied(tmp_path):
    _enable(tmp_path)
    assert SB.sandbox_check("quantum", "x", {}, str(tmp_path))["allow"] is False


def test_audit_log_written(tmp_path):
    _enable(tmp_path)
    SB.sandbox_check("exec", "run", {"code": "rm -rf /"}, str(tmp_path))
    log = tmp_path / ".psyclaw" / "sandbox_audit.jsonl"
    rec = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert rec["face"] == "exec" and rec["verdict"] == "deny"
    assert "code" in rec["args"]                           # 参数摘要留形状


def test_audit_summarizes_not_dumps_raw(tmp_path):
    _enable(tmp_path)
    SB.sandbox_check("exec", "run", {"code": "x" * 500}, str(tmp_path))
    log = tmp_path / ".psyclaw" / "sandbox_audit.jsonl"
    rec = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert len(rec["args"]["code"]) < 200 and "…(+" in rec["args"]["code"]


def test_policy_roundtrip_and_min_priv_merge(tmp_path):
    """坏档/缺键回默认(最小权限不被漏配削弱);往返可读。"""
    _enable(tmp_path, net={"upload": "deny"})              # 只写 net.upload
    pol = SB.load_policy(str(tmp_path))
    assert pol["enabled"] is True
    assert pol["net"]["upload"] == "deny"
    assert "api.openalex.org" in pol["net"]["allow_domains"]   # 默认白名单仍在
    assert pol["exec"]["deny_patterns"]                        # 默认拒绝模式仍在


def test_corrupt_policy_falls_back_to_default(tmp_path):
    p = tmp_path / ".psyclaw"
    p.mkdir(parents=True)
    (p / "sandbox.yaml").write_text("!!!not yaml{{{", encoding="utf-8")
    pol = SB.load_policy(str(tmp_path))
    assert pol["enabled"] is False                          # 坏档不放大权限


def test_yaml_parse_dump_shapes():
    text = SB._dump_yaml({"enabled": True,
                          "net": {"upload": "deny", "allow_domains": ["a.com", "b.org"]}})
    back = SB._parse_yaml(text)
    assert back["enabled"] is True
    assert back["net"]["allow_domains"] == ["a.com", "b.org"]
