"""带引用的轻量知识图谱(SQLite,stdlib only,无 Neo4j)。

把研究里的实体(构念/论文/人物/机构/技术…)与关系串起来,帮 Agent 理解全貌。核心纪律
(呼应「KG 最容易翻车,每条边必须带来源」)——**边由构造即带引用**:``add_edge`` 拒绝无
``source_ref`` 的边(反幻觉关系);``verify`` 复用 cite-check 的规范化,核对每条 citation 边的
来源是否真在检索语料里,溯源不到 = 疑似杜撰关系,报为孤儿。

- 主题范围、非全局:``seed_from_evidence_map`` 从既有 ``notes/evidence_map.json``
  (构念 × 支持文献,feat-007 合成产物)直接种出一张**天然带引用**的图。
- 存 ``.psyclaw/kg/graph.db``(与 recall 的 context 库并列);nodes 按 (归一名, 类型) 去重
  做基础实体消歧;edges 按 (src,dst,关系,来源) 去重。
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _norm(name: str) -> str:
    """基础实体归一(消歧):小写 + 去首尾 + 折叠内部空白。"""
    return re.sub(r"\s+", " ", (name or "").strip().lower())


class KnowledgeGraph:
    def __init__(self, project_dir: str | Path = ".") -> None:
        self.dir = Path(project_dir) / ".psyclaw" / "kg"
        self.db_path = self.dir / "graph.db"
        self._conn: sqlite3.Connection | None = None

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.executescript(
                "CREATE TABLE IF NOT EXISTS nodes("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " name TEXT, norm TEXT, type TEXT, UNIQUE(norm, type));"
                "CREATE TABLE IF NOT EXISTS edges("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " src INTEGER, dst INTEGER, relation TEXT,"
                " source_ref TEXT, source_kind TEXT, created TEXT,"
                " UNIQUE(src, dst, relation, source_ref));")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # -- 写入 ----------------------------------------------------------------
    def add_node(self, name: str, type: str) -> int:
        db = self._db()
        db.execute("INSERT OR IGNORE INTO nodes(name, norm, type) VALUES(?,?,?)",
                   (name, _norm(name), type))
        row = db.execute("SELECT id FROM nodes WHERE norm=? AND type=?",
                         (_norm(name), type)).fetchone()
        db.commit()
        return row[0]

    def add_edge(self, src_name: str, src_type: str, relation: str,
                 dst_name: str, dst_type: str, source_ref: str,
                 source_kind: str = "citation") -> int | None:
        """加一条**带来源**的关系边。``source_ref`` 为空 → 拒绝(返回 None,反幻觉关系)。"""
        if not (source_ref and source_ref.strip()):
            return None
        db = self._db()
        sid = self.add_node(src_name, src_type)
        did = self.add_node(dst_name, dst_type)
        db.execute(
            "INSERT OR IGNORE INTO edges(src, dst, relation, source_ref, source_kind, created)"
            " VALUES(?,?,?,?,?,?)",
            (sid, did, relation, source_ref.strip(), source_kind, _now()))
        row = db.execute(
            "SELECT id FROM edges WHERE src=? AND dst=? AND relation=? AND source_ref=?",
            (sid, did, relation, source_ref.strip())).fetchone()
        db.commit()
        return row[0] if row else None

    # -- 查询 ----------------------------------------------------------------
    def _node_id(self, name: str, type: str | None = None):
        db = self._db()
        if type:
            r = db.execute("SELECT id FROM nodes WHERE norm=? AND type=?",
                           (_norm(name), type)).fetchone()
        else:
            r = db.execute("SELECT id FROM nodes WHERE norm=?", (_norm(name),)).fetchone()
        return r[0] if r else None

    def neighbors(self, name: str, type: str | None = None) -> list[dict]:
        """某实体的直接关系边(出边 + 入边)。"""
        db = self._db()
        nid = self._node_id(name, type)
        if nid is None:
            return []
        out: list[dict] = []
        for eid, dst, rel, ref, kind in db.execute(
                "SELECT id, dst, relation, source_ref, source_kind FROM edges WHERE src=?",
                (nid,)).fetchall():
            other = db.execute("SELECT name, type FROM nodes WHERE id=?", (dst,)).fetchone()
            out.append({"relation": rel, "dir": "→", "other": other[0],
                        "other_type": other[1], "source_ref": ref, "source_kind": kind})
        for eid, src, rel, ref, kind in db.execute(
                "SELECT id, src, relation, source_ref, source_kind FROM edges WHERE dst=?",
                (nid,)).fetchall():
            other = db.execute("SELECT name, type FROM nodes WHERE id=?", (src,)).fetchone()
            out.append({"relation": rel, "dir": "←", "other": other[0],
                        "other_type": other[1], "source_ref": ref, "source_kind": kind})
        return out

    def subgraph(self, name: str, depth: int = 1) -> dict:
        """以某实体为中心的 ego 子图(BFS depth 层)。返回 {center, nodes, edges}。"""
        db = self._db()
        start = self._node_id(name)
        if start is None:
            return {"center": name, "nodes": [], "edges": []}
        seen_n: set[int] = {start}
        frontier = {start}
        edges: list[dict] = []
        seen_e: set[int] = set()
        for _ in range(max(1, depth)):
            nxt: set[int] = set()
            for nid in frontier:
                for eid, s, d, rel, ref in db.execute(
                        "SELECT id, src, dst, relation, source_ref FROM edges"
                        " WHERE src=? OR dst=?", (nid, nid)).fetchall():
                    if eid not in seen_e:
                        seen_e.add(eid)
                        edges.append({"src": s, "dst": d, "relation": rel, "source_ref": ref})
                    for other in (s, d):
                        if other not in seen_n:
                            seen_n.add(other)
                            nxt.add(other)
            frontier = nxt
        nodes = [{"id": nid, **dict(zip(("name", "type"),
                 db.execute("SELECT name, type FROM nodes WHERE id=?", (nid,)).fetchone()))}
                 for nid in seen_n]
        return {"center": name, "nodes": nodes, "edges": edges}

    def stats(self) -> dict:
        if not self.db_path.exists():
            return {"nodes": 0, "edges": 0, "uncited": 0}
        db = self._db()
        n = db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        e = db.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        # 由构造应恒为 0(add_edge 拒绝无来源);仍显式统计以自证不变量。
        uncited = db.execute(
            "SELECT COUNT(*) FROM edges WHERE source_ref IS NULL OR TRIM(source_ref)=''"
        ).fetchone()[0]
        return {"nodes": n, "edges": e, "uncited": uncited}

    # -- 从既有 evidence_map 种图(天然带引用)-------------------------------
    def seed_from_evidence_map(self, project_dir: str = ".") -> dict:
        """从 notes/evidence_map.json(构念 × 支持文献)种出带引用的图。返回计数。"""
        emap_p = Path(project_dir) / "notes" / "evidence_map.json"
        if not emap_p.exists():
            return {"added": 0, "error": "无 notes/evidence_map.json(先跑 lit --synthesize)"}
        try:
            emap = json.loads(emap_p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return {"added": 0, "error": f"evidence_map 不可解析:{exc}"}
        added = 0
        for theme in emap.get("themes", []):
            term = theme.get("term")
            if not term:
                continue
            for key in theme.get("cites", []):
                if self.add_edge(term, "construct", "研究见于", key, "paper",
                                 source_ref=key, source_kind="citation") is not None:
                    added += 1
        return {"added": added, **self.stats()}

    # -- 核验:每条 citation 边的来源须真在检索语料里(复用 cite-check 规范化)----
    def verify(self, project_dir: str = ".") -> dict:
        """核对 citation 边来源是否溯源到检索命中。孤儿边=来源不在语料=疑似杜撰关系。"""
        from psyclaw.psych.citations import _canon_key, load_allowed
        keys, source = load_allowed(project_dir)
        allowed = {c for k in keys if (c := _canon_key(k))}
        db = self._db()
        rows = db.execute(
            "SELECT e.id, e.relation, e.source_ref, e.source_kind,"
            " ns.name, nd.name FROM edges e"
            " JOIN nodes ns ON ns.id=e.src JOIN nodes nd ON nd.id=e.dst").fetchall()
        n_citation = sum(1 for r in rows if r[3] == "citation")
        if not allowed:
            # 评审修复:无检索语料 = 「无从核验」,不是「全是杜撰」——与 citations 的
            # manual_review 语义一致(fail-closed 只对**检出的**孤儿,不对不可判)。
            return {"total_edges": len(rows), "citation_edges": n_citation,
                    "corpus_source": None, "grounded": 0, "orphans": [],
                    "no_orphan_relations": True, "manual_review": True,
                    "note": "无检索语料(evidence_map/lit_search 缺失),关系溯源需人工核"}
        orphans: list[dict] = []
        checked = 0
        for eid, rel, ref, kind, sname, dname in rows:
            if kind != "citation":       # 非引用来源(session/url/manual)不在此核
                continue
            checked += 1
            canon = _canon_key(ref)
            if canon is None or canon not in allowed:
                orphans.append({"edge": f"{sname} —{rel}→ {dname}", "source_ref": ref})
        return {"total_edges": len(rows), "citation_edges": checked,
                "corpus_source": source, "grounded": checked - len(orphans),
                "orphans": orphans, "no_orphan_relations": len(orphans) == 0,
                "manual_review": False}


def _mmd_label(s: str) -> str:
    """mermaid 标签转义:双引号与竖线会破坏语法(评审修复,经真实渲染器验证)。"""
    return (s or "").replace('"', "'").replace("|", "/")


def render_mermaid(sub: dict) -> str:
    """ego 子图 → mermaid flowchart(每条边标注来源引用)。

    评审修复:裸 `"名字"` 不是合法的 flowchart 节点——必须 `nK["标签"]` 形式,
    否则所有产出图都渲染失败;关系/引用里的 `|` 也须转义(会截断边标签)。
    """
    ordered = sorted(sub.get("nodes", []), key=lambda n: n["id"])
    mid = {n["id"]: f"n{i}" for i, n in enumerate(ordered)}
    lines = ["```mermaid", "graph LR"]
    for n in ordered:
        lines.append(f'  {mid[n["id"]]}["{_mmd_label(n["name"])[:60]}"]')
    for e in sub.get("edges", []):
        s = mid.get(e["src"], "n_")
        d = mid.get(e["dst"], "n_")
        rel = _mmd_label(e.get("relation", ""))
        ref = _mmd_label(e.get("source_ref", ""))[:40]
        lines.append(f"  {s} -->|{rel} · {ref}| {d}")
    lines.append("```")
    return "\n".join(lines)
