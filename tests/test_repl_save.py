"""「天然」保存文件测试 —— parse_save_blocks(纯)+ apply_save_block 护栏。"""

from __future__ import annotations

from pathlib import Path

from psyclaw.repl import apply_save_block, parse_save_blocks, _save_is_protected


def test_parse_single_block():
    reply = "好的,内容如下:\n```save path=method.txt\nline1\nline2\n```\n已生成。"
    blocks = parse_save_blocks(reply)
    assert len(blocks) == 1
    assert blocks[0]["path"] == "method.txt"
    assert blocks[0]["content"] == "line1\nline2"


def test_parse_multiple_and_bare_and_quoted():
    reply = ("```save method.txt\nA\n```\n"
             "```save path=notes/b.md\nB body\n```\n"
             '```save path="my file.txt"\nC\n```')
    blocks = parse_save_blocks(reply)
    paths = [b["path"] for b in blocks]
    assert paths == ["method.txt", "notes/b.md", "my file.txt"]


def test_parse_windows_path():
    reply = "```save path=F:\\Study\\a\\method.txt\n研究内容\n```"
    blocks = parse_save_blocks(reply)
    assert blocks[0]["path"] == "F:\\Study\\a\\method.txt"
    assert blocks[0]["content"] == "研究内容"


def test_parse_none():
    assert parse_save_blocks("普通回复,没有 save 块。") == []


def test_protected_raw():
    assert _save_is_protected(Path("data/raw/secret.csv")) is True
    assert _save_is_protected(Path("data/clean/x.csv")) is False
    assert _save_is_protected(Path("notes/method.txt")) is False


def test_apply_saves_new_file(tmp_path):
    target = tmp_path / "out" / "method.txt"
    r = apply_save_block({"path": str(target), "content": "研究方法正文"})
    assert r["status"] == "saved"
    assert target.read_text(encoding="utf-8") == "研究方法正文"


def test_apply_refuses_data_raw(tmp_path):
    target = tmp_path / "data" / "raw" / "x.txt"
    r = apply_save_block({"path": str(target), "content": "x"})
    assert r["status"] == "refused-raw"
    assert not target.exists()


def test_apply_skips_existing_without_confirm(tmp_path):
    target = tmp_path / "m.txt"
    target.write_text("old", encoding="utf-8")
    r = apply_save_block({"path": str(target), "content": "new"})
    assert r["status"] == "skipped-exists"
    assert target.read_text(encoding="utf-8") == "old"   # 未覆盖


def test_apply_overwrites_with_confirm(tmp_path):
    target = tmp_path / "m.txt"
    target.write_text("old", encoding="utf-8")
    r = apply_save_block({"path": str(target), "content": "new"}, confirm=lambda p: True)
    assert r["status"] == "saved"
    assert target.read_text(encoding="utf-8") == "new"
