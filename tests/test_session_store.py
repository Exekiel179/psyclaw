"""会话持久化 store 测试(feat-013)—— sessions 元数据 + FTS5/LIKE 全文检索 + 生命周期。"""

from __future__ import annotations

from psyclaw.embed import get_embedder
from psyclaw.recall import ContextArchive


def _archive(tmp_path):
    # 注入哈希 embedder:离线、快、确定;向量非本特性关注点。
    return ContextArchive(str(tmp_path), embedder=get_embedder(prefer="hash"))


def test_record_creates_session_and_turn(tmp_path):
    a = _archive(tmp_path)
    a.record("s1", "问题 anxiety", "回答")
    sessions = a.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["id"] == "s1"
    assert sessions[0]["n_turns"] == 1
    turns = a.session_turns("s1")
    assert turns and turns[0]["user_text"] == "问题 anxiety"


def test_ensure_session_idempotent(tmp_path):
    a = _archive(tmp_path)
    a.ensure_session("s1")
    a.ensure_session("s1")
    assert len(a.list_sessions()) == 1


def test_rename_session(tmp_path):
    a = _archive(tmp_path)
    a.record("s1", "u", "r")
    assert a.rename_session("s1", "焦虑研究会话") is True
    assert a.list_sessions()[0]["name"] == "焦虑研究会话"


def test_list_sessions_counts_and_membership(tmp_path):
    a = _archive(tmp_path)
    a.record("A", "u1", "r1")
    a.record("A", "u2", "r2")
    a.record("B", "u3", "r3")
    by_id = {s["id"]: s for s in a.list_sessions()}
    assert by_id["A"]["n_turns"] == 2
    assert by_id["B"]["n_turns"] == 1


def test_session_turns_in_order(tmp_path):
    a = _archive(tmp_path)
    a.record("s1", "first", "r1")
    a.record("s1", "second", "r2")
    turns = a.session_turns("s1")
    assert [t["user_text"] for t in turns] == ["first", "second"]


def test_search_fts_finds_term(tmp_path):
    a = _archive(tmp_path)
    a.record("s1", "我在做 anxiety 焦虑 的研究", "关于 depression")
    a.record("s2", "完全无关的内容 sampling", "reply")
    assert a._db() is not None and a._fts is True  # 本机 FTS5 可用
    hits_en = a.search("anxiety")
    assert any(h["session"] == "s1" for h in hits_en)
    hits_cn = a.search("焦虑")
    assert any(h["session"] == "s1" for h in hits_cn)
    assert all("sampling" not in h["user_text"] for h in hits_en)


def test_search_like_fallback(tmp_path):
    a = _archive(tmp_path)
    a._db()
    a._fts = False  # 模拟无 FTS5 环境 → 走 LIKE 子串
    a.record("s1", "焦虑抑郁共病", "reply")
    hits = a.search("抑郁")  # 子串命中(LIKE)
    assert any(h["session"] == "s1" for h in hits)


def test_search_empty_returns_empty(tmp_path):
    a = _archive(tmp_path)
    a.record("s1", "u", "r")
    assert a.search("") == []
    assert a.search("   ") == []


def test_delete_session(tmp_path):
    a = _archive(tmp_path)
    a.record("A", "keep…anxiety", "r")
    a.record("A", "u2", "r2")
    a.record("B", "u3", "r3")
    assert a.delete_session("A") == 2
    ids = {s["id"] for s in a.list_sessions()}
    assert ids == {"B"}
    assert a.session_turns("A") == []
    assert all(h["session"] != "A" for h in a.search("anxiety"))


def test_fts_backfill_from_fallback(tmp_path):
    # 先在「无 FTS」状态落库,再用新连接(FTS 开)打开 → _init_fts 应回填并可检索。
    a1 = _archive(tmp_path)
    a1._db()
    a1._fts = False
    a1.record("s1", "backfilled anxiety content", "reply")
    a1.close()
    a2 = _archive(tmp_path)          # 新连接,FTS 自动探测开启 + 回填
    assert a2._db() is not None and a2._fts is True
    hits = a2.search("anxiety")
    assert any("backfilled" in h["user_text"] for h in hits)


def test_backfill_sessions_from_legacy_turns(tmp_path):
    # 旧库只有 turns、无 sessions 行 → 打开时应回填会话元数据。
    a1 = _archive(tmp_path)
    db = a1._db()
    db.execute("INSERT INTO turns(session, ts, user_text, reply_text)"
               " VALUES('legacy','2026-01-01T00:00:00','u','r')")
    db.execute("DELETE FROM sessions WHERE id='legacy'")  # 模拟旧库缺元数据
    db.commit()
    a1.close()
    a2 = _archive(tmp_path)
    ids = {s["id"] for s in a2.list_sessions()}
    assert "legacy" in ids
