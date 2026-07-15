"""AJS(Awesome Journal Skills)期刊技能包安装器(feat-139,stdlib only)。

AJS 是单一 mono-repo(github.com/brycewang-stanford/awesome-journal-skills),
每个期刊一个顶层目录(命名不统一:AAAI-Skills / China-Economic-Quarterly-Skills /
中文刊拼音 Caijing-Yanjiu),包内是完整插件结构 <包>/skills/<技能>/SKILL.md。

psyclaw 定位:只**编排/消费**外部技能包,不重造任何期刊内容(与「统计外移」同源
哲学)。本模块四职责,各自可单测:

- ``list_packs``:GitHub git/trees API 拉顶层目录清单(小 JSON,进程内缓存);
- ``resolve_pack``:刊名 → 包目录,**纯函数**(归一化 + 别名表 + 近似候选,
  不引随机,可确定性单测);
- ``install_pack``:git 稀疏检出只下目标包(纯 git、可走镜像),**fail-safe**
  ——失败给手动命令,不抛;
- 错误出路(无网/无 git/克隆失败/歧义)均不中断调用方(start 向导)。
"""

from __future__ import annotations

import difflib
import json
import re
import urllib.request
from pathlib import Path

AJS_REPO_SLUG = "brycewang-stanford/awesome-journal-skills"
AJS_REPO_URL = f"https://github.com/{AJS_REPO_SLUG}"
_TREES_API = f"https://api.github.com/repos/{AJS_REPO_SLUG}/git/trees/HEAD"

_packs_cache: list[str] | None = None    # 进程内缓存(清单小且极少变)

# 英文缩写别名(归一化键 → 归一化目标)。资深研究者惯用缩写报刊名;
# 表可按需扩,零命中时 resolve 仍会给近似候选兜底。
ALIASES = {
    "aer": "americaneconomicreview",
    "qje": "quarterlyjournalofeconomics",
    "jpe": "journalofpoliticaleconomy",
    "jf": "journaloffinance",
    "jfe": "journaloffinancialeconomics",
    "ms": "managementscience",
    "amj": "academyofmanagementjournal",
    "amr": "academyofmanagementreview",
    "asq": "administrativesciencequarterly",
    "jpsp": "journalofpersonalityandsocialpsychology",
    "pnas": "pnas",
}

# 中文刊显示名 → 归一化目录(AJS 中文刊用拼音目录)。零命中仍走近似候选。
CN_ALIASES = {
    "财经研究": "caijingyanjiu",
    "经济研究": "jingjiyanjiu",
    "管理世界": "guanlishijie",
    "经济学季刊": "chinaeconomicquarterly",
    "经济学(季刊)": "chinaeconomicquarterly",
    "中国经济季刊": "chinaeconomicquarterly",
    "心理学报": "xinlixuebao",
    "心理科学": "xinlikexue",
}


def _norm(name: str) -> str:
    """归一化:小写、去所有非字母数字(含连字符/空格/点),去尾缀 skills。"""
    s = re.sub(r"[^0-9a-z一-鿿]+", "", (name or "").lower())
    if s.endswith("skills"):
        s = s[: -len("skills")]
    return s


def list_packs(timeout: float = 8.0) -> dict:
    """拉 AJS 顶层目录清单。返回 {"ok", "packs", "note"};无网 fail-safe 不抛。"""
    global _packs_cache
    if _packs_cache is not None:
        return {"ok": True, "packs": list(_packs_cache), "note": "(缓存)"}
    try:
        req = urllib.request.Request(
            _TREES_API, headers={"User-Agent": "psyclaw-ajs",
                                 "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        packs = [e["path"] for e in data.get("tree", [])
                 if e.get("type") == "tree" and not e.get("path", ".").startswith(".")]
        _packs_cache = packs
        return {"ok": True, "packs": list(packs), "note": ""}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "packs": [], "note": f"拉取 AJS 目录失败:{exc}"}


def resolve_pack(journal_name: str, packs: list[str]) -> dict:
    """刊名 → AJS 包目录。纯函数,返回 {"match": str|None, "candidates": [...]}。

    唯一命中 → match;多候选/零命中 → candidates(零命中给确定性的近似建议)。
    """
    key = _norm(journal_name)
    if not key:
        return {"match": None, "candidates": []}
    key = CN_ALIASES.get(journal_name.strip(), ALIASES.get(key, key))
    key = _norm(key)
    norm_map = {_norm(p): p for p in packs}
    if key in norm_map:                                  # 1) 精确
        return {"match": norm_map[key], "candidates": [norm_map[key]]}
    cands = [p for n, p in norm_map.items()             # 2) 子串(双向)
             if len(key) >= 3 and (key in n or n in key)]
    if len(cands) == 1:
        return {"match": cands[0], "candidates": cands}
    if cands:
        return {"match": None, "candidates": sorted(cands)}
    close = difflib.get_close_matches(key, list(norm_map), n=5, cutoff=0.6)
    return {"match": None, "candidates": [norm_map[n] for n in close]}


def _manual_cmds(repo_url: str, pack_dir: str, dest) -> str:
    """给用户可直接复制的手动稀疏检出命令(fail-safe 出路)。"""
    return (f"  git clone --filter=blob:none --no-checkout --depth 1 {repo_url} _ajs\n"
            f"  git -C _ajs sparse-checkout set \"{pack_dir}\"\n"
            f"  git -C _ajs checkout\n"
            f"  mv \"_ajs/{pack_dir}\" \"{dest}/\" && rm -rf _ajs")


def _git(argv: list[str], timeout: int = 180) -> tuple[bool, str]:
    import subprocess
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stderr or r.stdout or "").strip()
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _sparse_checkout(url: str, pack_dir: str, workdir: Path) -> tuple[bool, str]:
    repo = workdir / "repo"
    for argv in (
        ["git", "clone", "--filter=blob:none", "--no-checkout", "--depth", "1",
         url, str(repo)],
        ["git", "-C", str(repo), "sparse-checkout", "set", pack_dir],
        ["git", "-C", str(repo), "checkout"],
    ):
        ok, err = _git(argv)
        if not ok:
            return False, err
    if not (repo / pack_dir).is_dir():
        return False, f"仓库中无目录 {pack_dir}"
    return True, ""


def install_pack(pack_dir: str, dest, repo_url: str = AJS_REPO_URL) -> dict:
    """git 稀疏检出把 AJS 包装到 dest/<pack_dir>。

    返回 {"ok", "path", "note", "mirror"}。fail-safe:无 git / 克隆失败
    (官方失败自动镜像重试)均返回手动命令提示,不抛。
    """
    import shutil
    import tempfile
    dest = Path(dest)
    target = dest / pack_dir
    if target.is_dir():
        return {"ok": True, "path": str(target), "note": "已存在(跳过安装)",
                "mirror": False}
    if not shutil.which("git"):
        return {"ok": False, "path": "", "mirror": False,
                "note": "未检测到 git。手动安装:\n" + _manual_cmds(repo_url, pack_dir, dest)}
    from psyclaw import mirror
    url = mirror.github_clone_url(repo_url)
    tried_mirror = url != repo_url
    workdir = Path(tempfile.mkdtemp(prefix="psyclaw-ajs-"))
    try:
        ok, err = _sparse_checkout(url, pack_dir, workdir)
        if not ok and not tried_mirror:                  # 官方失败 → 镜像重试
            murl = mirror.github_mirror_url(repo_url)
            if murl != url:
                shutil.rmtree(workdir, ignore_errors=True)
                workdir.mkdir(parents=True, exist_ok=True)
                ok, err = _sparse_checkout(murl, pack_dir, workdir)
                tried_mirror = True
        if not ok:
            return {"ok": False, "path": "", "mirror": tried_mirror,
                    "note": f"克隆失败({err})。手动安装:\n"
                            + _manual_cmds(repo_url, pack_dir, dest)}
        dest.mkdir(parents=True, exist_ok=True)
        shutil.move(str(workdir / "repo" / pack_dir), str(target))
        return {"ok": True, "path": str(target), "mirror": tried_mirror,
                "note": "已安装" + ("(经镜像)" if tried_mirror else "")}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "path": "", "mirror": tried_mirror,
                "note": f"安装失败({exc})。手动安装:\n"
                        + _manual_cmds(repo_url, pack_dir, dest)}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
