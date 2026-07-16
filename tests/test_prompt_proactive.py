"""feat-148:提示强化——模型主动读/跑(第一人称「我来」),一次只问一个问题。

真实事故(profile 对话 chat_20260716-013723):
- 模型写「请你手动查看 data/exploration/test_output.csv 文件,并回复以下关键日期的
  value 值」——把自己能做的读文件甩给用户;
- 模型写「请运行这个修复后的命令」——命令块其实会自动执行,措辞却让用户以为要手动跑;
- 模型写「为了确保后续步骤紧凑,我将以上问题整合为一次回答」——多个问题挤进一次。
"""
from __future__ import annotations

from psyclaw.repl import _CHOICES_SYSTEM, _READ_OPEN_SYSTEM, _RUN_SYSTEM


def test_read_prompt_forbids_delegating_to_user():
    p = _READ_OPEN_SYSTEM
    # 明确禁止「让用户手动打开/粘贴/报数字」
    assert "手动" in p or "粘贴" in p
    assert "我来读" in p or "我读" in p or "直接" in p


def test_run_prompt_first_person_not_ask_user():
    p = _RUN_SYSTEM
    assert "我来跑" in p or "我来运行" in p or "我运行" in p
    # 反面:禁止「请你运行/请运行」甩给用户
    assert "请你运行" in p or "让用户" in p or "别让用户" in p or "不要让用户" in p


def test_choices_prompt_forbids_multi_question():
    p = _CHOICES_SYSTEM
    assert "一次只" in p or "一个问题" in p
    assert "合并" in p or "整合" in p or "多个问题" in p


def test_system_prompt_carries_proactive_directives(monkeypatch):
    monkeypatch.setattr("psyclaw.config.load_config",
                        lambda: {"assist_level": "standard", "provider": "mock"})
    from psyclaw.repl import ReplSession
    rs = ReplSession.__new__(ReplSession)
    rs.file_access = "open"
    rs.plan_mode = False
    persist = rs._standing_conventions()
    assert "一个问题" in persist or "一次只" in persist
    assert "我来" in persist or "不要让用户" in persist
