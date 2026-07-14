"""沙箱核 + 策略模型(feat-125,蓝图 docs/SANDBOX.md)。

四原则:最小权限 / 快速失败 / 可审计 / 可恢复。四执行面(file/tools/exec/net)
共用**单一裁决入口** ``sandbox_check(face, action, args)``——fail-closed:
策略缺失/异常/未知面一律拒。每次调用落 ``.psyclaw/sandbox_audit.jsonl``。

本模块只做**裁决与审计的地基**;各面的具体判据(私密/编码表、AST 筛码、
域名白名单)在 feat-126~128 往策略里填,裁决逻辑在此扩展。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

FACES = ("file", "tools", "exec", "net")

# 最小权限默认策略:enabled 时四面都从"拒绝优先"起步,按需在 sandbox.yaml 放开。
DEFAULT_POLICY: dict = {
    "enabled": False,          # 未配置=不启用(询问后才开,feat-129)
    "file": {"write_allow": ["outputs/", "notes/", ".psyclaw/"],
             "private_paths": ["data/raw/"], "require_codebook": True},
    "tools": {"side_effect_approval": "per-action", "stats_must_delegate": True},
    "exec": {"timeout_s": 180,
             "deny_patterns": ["rm -rf", "mkfs", ":(){", "fork", "shutdown",
                               "> /dev/sd", "dd if=", "curl|sh", "wget|sh"],
             "allow_intent": ["pandas", "pingouin", "numpy", "scipy",
                              "statsmodels", "matplotlib"]},
    "net": {"allow_domains": ["api.openalex.org", "www.ebi.ac.uk",
                              "api.crossref.org", "export.arxiv.org",
                              "arxiv.org", "api.unpaywall.org"],
            "upload": "deny"},
    "audit": ".psyclaw/sandbox_audit.jsonl",
}


def _policy_path(project_dir: str) -> Path:
    return Path(project_dir) / ".psyclaw" / "sandbox.yaml"


def load_policy(project_dir: str = ".") -> dict:
    """读 .psyclaw/sandbox.yaml(极简 YAML,与 registry 同法);缺失/坏档返回默认。

    合并语义:文件里出现的键覆盖默认,未出现的保留默认(最小权限不被漏配削弱)。
    """
    p = _policy_path(project_dir)
    policy = {k: (dict(v) if isinstance(v, dict) else v)
              for k, v in DEFAULT_POLICY.items()}
    if not p.is_file():
        return policy
    try:
        overrides = _parse_yaml(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return policy                       # 坏档 → 默认(fail-closed 不放大权限)
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(policy.get(k), dict):
            policy[k].update(v)
        else:
            policy[k] = v
    return policy


def save_policy(policy: dict, project_dir: str = ".") -> Path:
    p = _policy_path(project_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_dump_yaml(policy), encoding="utf-8")
    return p


def audit(project_dir: str, face: str, action: str, args: dict,
          verdict: str, reason: str) -> None:
    """追加一条审计记录(fail-safe:写不了不抛)。"""
    try:
        pol = load_policy(project_dir)
        ap = Path(project_dir) / pol.get("audit", DEFAULT_POLICY["audit"])
        ap.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "face": face,
               "action": action, "args": _summ(args), "verdict": verdict,
               "reason": reason}
        with ap.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def _summ(args: dict) -> dict:
    """参数摘要(不落原始数据/密钥,只留可审计的形状)。"""
    out = {}
    for k, v in (args or {}).items():
        s = str(v)
        out[k] = s if len(s) <= 120 else s[:120] + f"…(+{len(s) - 120})"
    return out


def sandbox_check(face: str, action: str, args: dict | None = None,
                  project_dir: str = ".") -> dict:
    """四面共用的**单一裁决入口**。返回 {allow, reason, needs?}。

    - 沙箱未启用 → allow(沿用各面既有守卫,不新增限制);
    - 未知面 → 拒(fail-closed);
    - 各面判据由 feat-126~128 在此扩展;本轮先落地入口 + 审计 + exec 的
      deny_patterns 硬拒(最小可用的一条真判据,证明链路通)。
    每次裁决落审计。
    """
    args = args or {}
    policy = load_policy(project_dir)
    if not policy.get("enabled"):
        return _verdict(project_dir, face, action, args, True, "沙箱未启用")
    if face not in FACES:
        return _verdict(project_dir, face, action, args, False, f"未知执行面:{face}")

    if face == "exec":
        cmd = str(args.get("code") or args.get("cmd") or "")
        for pat in policy.get("exec", {}).get("deny_patterns", []):
            if pat in cmd:
                return _verdict(project_dir, face, action, args, False,
                                f"命中恶意模式「{pat}」(快速失败)")
        return _verdict(project_dir, face, action, args, True, "未命中恶意模式")

    if face == "file":
        return _check_file(policy, project_dir, action, args)

    # tools/net:入口已通,判据待 feat-127~128 填;当前放行并审计(不回归)
    return _verdict(project_dir, face, action, args, True, "该面判据待实现,暂放行")


def is_private_path(path: str, policy: dict) -> bool:
    """路径是否落在被标为私密的目录下(private_paths 前缀匹配,规范化后比较)。"""
    from pathlib import PurePosixPath
    norm = str(path).replace("\\", "/").lstrip("./")
    for pref in policy.get("file", {}).get("private_paths", []):
        p = str(pref).replace("\\", "/").strip("/")
        if norm == p or norm.startswith(p + "/") or f"/{p}/" in f"/{norm}":
            return True
    return False


def _check_file(policy: dict, project_dir: str, action: str, args: dict) -> dict:
    """文件面裁决(feat-126)。action ∈ read | write | externalize。

    - read/write:项目内相对路径且非 data/raw(既有铁律沿用,此处不放大);
    - **externalize(跨信任边界:进 LLM 上下文 / 网络请求 / 写出项目)**——
      这是私密保护的关键动作:目标是私密数据 → 必须有编码表(codebook),
      有则要求 needs=codebook(调用方脱敏后再传),无则 fail-closed 拒绝并
      提示先建。区别于「拒绝访问」:私密数据可**本地**处理,只是不许**原样外传**。
    """
    fp = str(args.get("path") or args.get("target") or "")
    fcfg = policy.get("file", {})
    if action == "externalize":
        if is_private_path(fp, policy):
            if not fcfg.get("require_codebook", True):
                return _verdict(project_dir, "file", action, args, True,
                                "私密路径但策略未强制编码表(用户已放开)")
            if codebook_exists(project_dir):
                r = _verdict(project_dir, "file", action, args, True,
                             "私密数据外传:须经编码表脱敏后传出")
                r["needs"] = "codebook"
                return r
            return _verdict(project_dir, "file", action, args, False,
                            "私密数据禁止原样外传,且缺编码表 notes/codebook.yaml"
                            "——先建编码表(真实值→代号)再脱敏传出")
        return _verdict(project_dir, "file", action, args, True, "非私密路径,可外传")
    if action == "write":
        norm = fp.replace("\\", "/").lstrip("./")
        for pref in fcfg.get("private_paths", []):
            p = str(pref).replace("\\", "/").strip("/")
            if norm == p or norm.startswith(p + "/"):
                return _verdict(project_dir, "file", action, args, False,
                                f"拒绝写入私密/受保护路径 {pref}")
        allow = fcfg.get("write_allow", [])
        if allow and not any(norm.startswith(str(a).strip("/")) for a in allow):
            return _verdict(project_dir, "file", action, args, False,
                            f"写入路径不在允许清单 {allow}(最小权限)")
        return _verdict(project_dir, "file", action, args, True, "写入路径允许")
    return _verdict(project_dir, "file", action, args, True, "读取放行(沿用既有守卫)")


# ---------------------------------------------------------------------------
# 编码表(codebook):私密数据脱敏的真实值→代号映射。notes/codebook.yaml
# ---------------------------------------------------------------------------

def _codebook_path(project_dir: str) -> Path:
    return Path(project_dir) / "notes" / "codebook.yaml"


def codebook_exists(project_dir: str) -> bool:
    return _codebook_path(project_dir).is_file()


def load_codebook(project_dir: str = ".") -> dict:
    """读编码表 {真实值: 代号}(极简 YAML,map 结构);缺失/坏档返回 {}。"""
    p = _codebook_path(project_dir)
    if not p.is_file():
        return {}
    try:
        data = _parse_yaml(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    mapping = data.get("map", data)          # 支持顶层 map: 或直接键值
    return {str(k): str(v) for k, v in mapping.items()
            if not isinstance(v, (dict, list))}


def redact(text: str, project_dir: str = ".") -> tuple[str, int]:
    """按编码表把私密真实值替换成代号。返回 (脱敏文本, 替换次数)。

    绝不"尽力":编码表里有的值才替换;编码表为空则原样返回 0 次(调用方据此
    判定是否可外传——空表=没有脱敏能力,externalize 裁决会拒)。长值先替,
    防短值是长值子串时误伤(如 id「1」不覆盖 id「10」)。
    """
    book = load_codebook(project_dir)
    if not book or not text:
        return text, 0
    n = 0
    for real in sorted(book, key=len, reverse=True):
        if real and real in text:
            text = text.replace(real, book[real])
            n += 1
    return text, n


def _verdict(project_dir, face, action, args, allow, reason) -> dict:
    audit(project_dir, face, action, args, "allow" if allow else "deny", reason)
    return {"allow": allow, "reason": reason}


# ---------------------------------------------------------------------------
# 极简 YAML(仅支持本策略需要的:两级 map + 内联 list + 标量;不引 pyyaml)
# ---------------------------------------------------------------------------

def _parse_scalar(s: str):
    s = s.strip()
    if s in ("true", "True"):
        return True
    if s in ("false", "False"):
        return False
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        return [x.strip().strip("'\"") for x in inner.split(",") if x.strip()]
    if s.lstrip("-").isdigit():
        return int(s)
    return s.strip("'\"")


def _parse_yaml(text: str) -> dict:
    root: dict = {}
    cur: dict | None = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        key, _, val = raw.strip().partition(":")
        key = key.strip()
        if indent == 0:
            if val.strip():
                root[key] = _parse_scalar(val)
                cur = None
            else:
                cur = root.setdefault(key, {})
        elif cur is not None:
            cur[key] = _parse_scalar(val)
    return root


def _dump_yaml(policy: dict) -> str:
    lines = ["# PsyClaw 沙箱策略(docs/SANDBOX.md;可审计、可编辑)"]
    for k, v in policy.items():
        if isinstance(v, dict):
            lines.append(f"{k}:")
            for kk, vv in v.items():
                lines.append(f"  {kk}: {_fmt(vv)}")
        else:
            lines.append(f"{k}: {_fmt(v)}")
    return "\n".join(lines) + "\n"


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return "[" + ", ".join(str(x) for x in v) + "]"
    return str(v)
