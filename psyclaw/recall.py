"""上下文召回 — 全量储存 + 关键词索引 + 本地语义向量,相关度门控读取。

工作流(按使用者的检索纪律设计):
1. **全量储存**:每轮对话(用户输入+助手回答)完整落库
   `.psyclaw/context/index.db`(SQLite,turns 表存全文)。
2. **双通道索引**:
   - 关键词通道:固定领域词表命中 + 英文术语 token → keywords 表;
   - 语义通道:本地 embedding(psyclaw.embed,model2vec 选装/哈希兜底)
     → embeddings 表(向量按后端模型名分桶,换模型自动惰性重建)。
3. **调用时定位**:新问题两路并查 ——
   关键词相关度 = |查询关键词 ∩ 轮次关键词| / |查询关键词|;
   语义相关度 = 查询向量与轮次向量的余弦。同轮次取更高者。
4. **相关度门控**:关键词门槛默认 0.8;语义门槛随后端走
   (真模型 0.8,哈希兜底 0.5)。不达标**不注入** ——
   召回不到就不召回,不拿弱相关内容污染上下文(与 gates 同款 fail-closed)。
"""

from __future__ import annotations

import re
import sqlite3
import struct
from datetime import datetime
from pathlib import Path

RECALL_THRESHOLD = 0.8          # 关键词通道门槛(80%;语义门槛见 embed 后端)
MAX_HITS = 3                    # 最多召回轮次
EXCERPT_CHARS = 800             # 每轮注入的截断长度

# 固定领域词表(心理学研究全流程;命中按整词条计)
FIXED_KEYWORDS = (
    # 统计方法
    "描述统计", "相关分析", "回归", "t检验", "方差分析", "anova", "ancova",
    "卡方", "中介", "调节", "交互作用", "多重比较", "非参数", "bootstrap",
    "贝叶斯", "效应量", "置信区间", "功效分析", "样本量", "正态", "方差齐性",
    "异常值", "缺失值", "重编码", "信度", "效度", "因子分析", "cfa", "efa",
    "sem", "结构方程", "潜变量", "测量不变性", "mlm", "多层模型", "lavaan",
    "lme4", "pingouin", "统计检验", "假设检验", "p值", "显著性",
    # 设计与流程
    "实验设计", "被试间", "被试内", "混合设计", "纵向", "追踪", "esm",
    "预注册", "随机分组", "对照组", "问卷", "量表", "操纵检验",
    # 文献与写作
    "文献综述", "文献检索", "prisma", "元分析", "apa", "论文", "写作",
    "审稿", "引用", "摘要", "投稿", "撤稿",
    # 领域与工具
    "焦虑", "抑郁", "正念", "认知", "情绪", "人格", "eeg", "erp", "脑电",
    "fmri", "反应时", "spss", "mplus", "stata", "zotero", "jasp",
    "数据清洗", "草率作答", "数据质量",
)

_EN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_EN_STOP = {
    "the", "and", "for", "with", "that", "this", "are", "was", "you",
    "not", "but", "can", "all", "any", "use", "has", "have", "from",
    "csv", "tsv", "data", "file", "task_done", "verdict",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def extract_keywords(text: str) -> set[str]:
    """固定词表命中 + 英文术语 token。抽不到就是空集,不猜。"""
    low = (text or "").lower()
    kws = {kw for kw in FIXED_KEYWORDS if kw in low}
    kws |= {t for t in (m.group(0).lower() for m in _EN_TOKEN_RE.finditer(low))
            if t not in _EN_STOP and len(t) >= 3}
    return kws


class ContextArchive:
    """SQLite 全量上下文库 + 关键词索引 + 本地向量(双通道召回)。"""

    def __init__(self, project_dir: str | Path = ".", embedder=None) -> None:
        self.dir = Path(project_dir) / ".psyclaw" / "context"
        self.db_path = self.dir / "index.db"
        self._conn: sqlite3.Connection | None = None
        self._embedder = embedder          # None → 首次使用时 get_embedder()
        self._fts: bool | None = None      # FTS5 是否可用(建连时探测;不可用回落 LIKE)

    @property
    def embedder(self):
        if self._embedder is None:
            from psyclaw.embed import get_embedder
            self._embedder = get_embedder()
        return self._embedder

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.executescript(
                "CREATE TABLE IF NOT EXISTS turns("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " session TEXT, ts TEXT, user_text TEXT, reply_text TEXT);"
                "CREATE TABLE IF NOT EXISTS keywords("
                " turn_id INTEGER, kw TEXT,"
                " UNIQUE(turn_id, kw));"
                "CREATE INDEX IF NOT EXISTS idx_kw ON keywords(kw);"
                "CREATE TABLE IF NOT EXISTS embeddings("
                " turn_id INTEGER, model TEXT, dim INTEGER, vec BLOB,"
                " UNIQUE(turn_id, model));"
                # 会话元数据(feat-013):id 与 turns.session 对应,name 供 resume/rename。
                "CREATE TABLE IF NOT EXISTS sessions("
                " id TEXT PRIMARY KEY, name TEXT, created TEXT, updated TEXT);")
            # 旧库里已有 turns 但无 sessions 行 → 从既有轮次回填会话元数据。
            self._conn.execute(
                "INSERT OR IGNORE INTO sessions(id, name, created, updated)"
                " SELECT session, session, MIN(ts), MAX(ts) FROM turns"
                " WHERE session IS NOT NULL GROUP BY session")
            self._fts = self._init_fts(self._conn)
            self._conn.commit()
        return self._conn

    def _init_fts(self, conn: sqlite3.Connection) -> bool:
        """探测并建 FTS5 全文索引;不可用(未编译 FTS5)则回落 LIKE。"""
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5("
                " turn_id UNINDEXED, session UNINDEXED, body)")
        except sqlite3.OperationalError:
            return False
        # 回填:回落期(或本次刚建索引)落库的历史轮次补进 FTS。
        try:
            conn.execute(
                "INSERT INTO turns_fts(turn_id, session, body)"
                " SELECT t.id, t.session, t.user_text || char(10) || t.reply_text"
                " FROM turns t WHERE NOT EXISTS"
                "  (SELECT 1 FROM turns_fts f WHERE f.turn_id = t.id)")
        except sqlite3.OperationalError:
            pass
        return True

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # -- 写入:全量储存 + 关键词索引 + 向量 -----------------------------------
    def record(self, session: str, user_text: str, reply_text: str) -> int:
        db = self._db()
        self.ensure_session(session)
        cur = db.execute(
            "INSERT INTO turns(session, ts, user_text, reply_text) VALUES(?,?,?,?)",
            (session, _now(), user_text, reply_text))
        turn_id = cur.lastrowid
        for kw in extract_keywords(user_text + "\n" + reply_text):
            db.execute("INSERT OR IGNORE INTO keywords(turn_id, kw) VALUES(?,?)",
                       (turn_id, kw))
        try:
            self._store_vec(db, turn_id, user_text + "\n" + reply_text)
        except Exception:  # noqa: BLE001  # 向量失败不影响全量储存与关键词
            pass
        if self._fts:
            try:
                db.execute(
                    "INSERT INTO turns_fts(turn_id, session, body) VALUES(?,?,?)",
                    (turn_id, session, user_text + "\n" + reply_text))
            except sqlite3.OperationalError:  # FTS 写失败不影响全量储存
                pass
        db.execute("UPDATE sessions SET updated=? WHERE id=?", (_now(), session))
        db.commit()
        return turn_id

    # -- 会话生命周期(feat-013:sessions 元数据 + FTS 全文检索,供 resume/rename) -----
    def ensure_session(self, session_id: str, name: str | None = None) -> None:
        """确保会话元数据行存在(幂等)。name 缺省用 session_id。"""
        db = self._db()
        db.execute(
            "INSERT OR IGNORE INTO sessions(id, name, created, updated) VALUES(?,?,?,?)",
            (session_id, name or session_id, _now(), _now()))
        db.commit()

    def rename_session(self, session_id: str, name: str) -> bool:
        """给会话改名(不存在则先建)。返回是否有行受影响。"""
        db = self._db()
        self.ensure_session(session_id)
        cur = db.execute("UPDATE sessions SET name=? WHERE id=?", (name, session_id))
        db.commit()
        return cur.rowcount > 0

    def list_sessions(self, limit: int = 50) -> list[dict]:
        """列出会话(按最近更新降序):{id, name, created, updated, n_turns}。"""
        db = self._db()
        rows = db.execute(
            "SELECT s.id, s.name, s.created, s.updated,"
            " (SELECT COUNT(*) FROM turns t WHERE t.session = s.id) AS n"
            " FROM sessions s ORDER BY s.updated DESC LIMIT ?", (limit,)).fetchall()
        return [{"id": r[0], "name": r[1], "created": r[2], "updated": r[3],
                 "n_turns": r[4]} for r in rows]

    def session_turns(self, session_id: str) -> list[dict]:
        """取某会话的全部轮次(时间顺序),供 resume 重建对话历史。"""
        db = self._db()
        rows = db.execute(
            "SELECT ts, user_text, reply_text FROM turns WHERE session=? ORDER BY id",
            (session_id,)).fetchall()
        return [{"ts": r[0], "user_text": r[1], "reply_text": r[2]} for r in rows]

    def _fts_query(self, query: str) -> str:
        """把用户查询清成安全的 FTS5 MATCH 串(逐 token 引号包裹,隐式 AND)。"""
        toks = re.findall(r"[0-9A-Za-z一-鿿]+", query or "")
        return " ".join(f'"{t}"' for t in toks[:16])

    def _hydrate(self, db: sqlite3.Connection, rows: list) -> list[dict]:
        out: list[dict] = []
        for tid, sess in rows:
            row = db.execute(
                "SELECT ts, user_text, reply_text FROM turns WHERE id=?",
                (tid,)).fetchone()
            if row:
                out.append({"id": tid, "session": sess, "ts": row[0],
                            "user_text": row[1], "reply_text": row[2]})
        return out

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """跨会话全文检索。FTS5 可用走 MATCH(bm25 排序),否则回落 LIKE 子串。

        返回 [{id, session, ts, user_text, reply_text}]。无查询词返回 []。
        """
        db = self._db()
        q = (query or "").strip()
        if not q:
            return []
        if self._fts:
            match = self._fts_query(q)
            if match:
                try:
                    rows = db.execute(
                        "SELECT turn_id, session FROM turns_fts"
                        " WHERE turns_fts MATCH ? ORDER BY rank LIMIT ?",
                        (match, limit)).fetchall()
                    hits = self._hydrate(db, rows)
                    if hits:
                        return hits
                    # FTS 零命中 → 继续走 LIKE(评审修复:unicode61 把连续中文当一个
                    # token,「量表」这类子串在 FTS 永远不命中;不能让空结果压住兜底)
                except sqlite3.OperationalError:
                    pass  # 回落 LIKE
        like = f"%{q}%"
        rows = db.execute(
            "SELECT id, session FROM turns WHERE user_text LIKE ? OR reply_text LIKE ?"
            " ORDER BY id DESC LIMIT ?", (like, like, limit)).fetchall()
        return self._hydrate(db, rows)

    def delete_session(self, session_id: str) -> int:
        """删除某会话的全部轮次(含关键词/向量/FTS)与元数据。返回删除轮次数。"""
        db = self._db()
        tids = [r[0] for r in db.execute(
            "SELECT id FROM turns WHERE session=?", (session_id,)).fetchall()]
        for tid in tids:
            db.execute("DELETE FROM keywords WHERE turn_id=?", (tid,))
            db.execute("DELETE FROM embeddings WHERE turn_id=?", (tid,))
            if self._fts:
                try:
                    db.execute("DELETE FROM turns_fts WHERE turn_id=?", (tid,))
                except sqlite3.OperationalError:
                    pass
        db.execute("DELETE FROM turns WHERE session=?", (session_id,))
        db.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        db.commit()
        return len(tids)

    def _store_vec(self, db: sqlite3.Connection, turn_id: int, text: str) -> None:
        emb = self.embedder
        vec = emb.encode([text])[0]
        db.execute(
            "INSERT OR REPLACE INTO embeddings(turn_id, model, dim, vec)"
            " VALUES(?,?,?,?)",
            (turn_id, emb.name, len(vec), struct.pack(f"{len(vec)}f", *vec)))

    def reindex(self) -> int:
        """给缺当前模型向量的轮次补向量(装了新 embedding 模型后调用)。"""
        db = self._db()
        emb = self.embedder
        rows = db.execute(
            "SELECT t.id, t.user_text, t.reply_text FROM turns t"
            " WHERE NOT EXISTS (SELECT 1 FROM embeddings e"
            "  WHERE e.turn_id = t.id AND e.model = ?)",
            (emb.name,)).fetchall()
        if not rows:
            return 0
        vecs = emb.encode([f"{u}\n{r}" for _, u, r in rows])
        for (tid, _, _), vec in zip(rows, vecs):
            db.execute(
                "INSERT OR REPLACE INTO embeddings(turn_id, model, dim, vec)"
                " VALUES(?,?,?,?)",
                (tid, emb.name, len(vec), struct.pack(f"{len(vec)}f", *vec)))
        db.commit()
        return len(rows)

    # -- 读取:双通道定位 → 相关度门控 ----------------------------------------
    def recall(self, query: str, threshold: float = RECALL_THRESHOLD,
               limit: int = MAX_HITS, exclude_session: str | None = None,
               sem_threshold: float | None = None) -> list[dict]:
        """返回相关度达标的历史轮次;不达标返回 [](不注入弱相关)。

        threshold:关键词通道门槛;sem_threshold:语义通道门槛,
        默认随 embedding 后端(真模型 0.8 / 哈希兜底 0.5)。
        """
        db = self._db()
        scored: dict[int, tuple[float, str]] = {}   # tid → (score, channel)

        # 通道 1:关键词覆盖率
        q_kws = extract_keywords(query)
        if q_kws:
            marks = ",".join("?" * len(q_kws))
            for tid, cnt in db.execute(
                    f"SELECT turn_id, COUNT(DISTINCT kw) FROM keywords"
                    f" WHERE kw IN ({marks}) GROUP BY turn_id",
                    tuple(q_kws)).fetchall():
                score = cnt / len(q_kws)
                if score >= threshold:
                    scored[tid] = (score, "关键词")

        # 通道 2:语义余弦(本地 embedding;失败只降级到关键词,不阻塞)
        try:
            from psyclaw.embed import cosine
            emb = self.embedder
            sem_th = sem_threshold if sem_threshold is not None \
                else emb.default_threshold
            self.reindex()                      # 惰性补齐当前模型的向量
            qv = emb.encode([query])[0]
            for tid, dim, blob in db.execute(
                    "SELECT turn_id, dim, vec FROM embeddings WHERE model=?",
                    (emb.name,)).fetchall():
                sim = cosine(qv, list(struct.unpack(f"{dim}f", blob)))
                if sim >= sem_th and sim > scored.get(tid, (0.0, ""))[0]:
                    scored[tid] = (sim, "语义")
        except Exception:  # noqa: BLE001
            pass

        ranked = sorted(scored.items(), key=lambda x: (-x[1][0], -x[0]))
        hits: list[dict] = []
        for tid, (score, channel) in ranked:
            sess, ts, u, r = db.execute(
                "SELECT session, ts, user_text, reply_text FROM turns WHERE id=?",
                (tid,)).fetchone()
            if exclude_session and sess == exclude_session:
                continue
            hits.append({"id": tid, "ts": ts, "score": score,
                         "channel": channel, "user_text": u, "reply_text": r})
            if len(hits) >= limit:
                break
        return hits

    def stats(self) -> tuple[int, int]:
        """(轮次数, 关键词条数)。"""
        if not self.db_path.exists():
            return (0, 0)
        db = self._db()
        n_turns = db.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
        n_kws = db.execute("SELECT COUNT(*) FROM keywords").fetchone()[0]
        return (n_turns, n_kws)


def render_recall(hits: list[dict]) -> str:
    """把召回结果渲染为注入 system 的上下文块。"""
    if not hits:
        return ""
    parts = ["# 历史上下文召回(关键词/语义双通道命中,相关度已过门槛)"]
    for h in hits:
        u = h["user_text"][:EXCERPT_CHARS]
        r = h["reply_text"][:EXCERPT_CHARS]
        parts.append(f"## {h['ts']} · 相关度 {h['score']:.0%}"
                     f"({h.get('channel', '关键词')})\n"
                     f"用户:{u}\n回答:{r}")
    parts.append("以上为历史召回,仅作背景;以当前问题为准。")
    return "\n\n".join(parts)
