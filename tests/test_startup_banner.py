"""feat-158:启动横幅美化——修 Preparation 挤字 + provider 行清理。"""
from __future__ import annotations

import re

from psyclaw import ui

_ANSI = re.compile(r"\033\[[0-9;]*m")


def _plain(s: str) -> str:
    return _ANSI.sub("", s)


def test_preparation_label_not_glued_to_value():
    """此前 kv 宽 10 但 'Preparation' 11 字 → 「Preparationnot started」挤在一起。"""
    status = {"project": "/x", "goal": "", "clarify": {"exists": False},
              "next": None}
    out = _plain(ui.startup("0.14.0", status=status))
    assert "Preparationnot" not in out
    assert "Preparation " in out or "Preparation\t" in out    # 标签与值间有空白


def test_labels_aligned():
    """所有状态行标签左对齐到同一列(值起始列一致)。"""
    status = {"project": "/proj", "goal": "某目标", "clarify": {"exists": False},
              "next": None}
    lines = _plain(ui.startup("0.14.0", status=status, provider="deepseek · x")).splitlines()
    # 取 Provider/Goal/Preparation 行,值前的标签区宽度应一致
    def label_gap(name):
        for ln in lines:
            if name in ln:
                i = ln.index(name)
                return ln[i + len(name):]
        return None
    # Goal(4)与 Preparation(11)标签不同长,但值都应对齐——即标签区总宽相同
    goal_line = next(ln for ln in lines if "Goal" in ln)
    prep_line = next(ln for ln in lines if "Preparation" in ln)
    goal_val_col = goal_line.index("某目标")
    # Preparation 行的值(not started)起始列应与 Goal 值列一致
    prep_val_col = prep_line.index("not started")
    assert goal_val_col == prep_val_col, "标签未对齐:值起始列不一致"


def test_provider_line_no_ugly_baseurl_truncation():
    """provider 行不该出现被截断的 base_url=h… 残片。"""
    prov = "deepseek · deepseek-v4-flash · key ✓"     # describe_short 形态
    out = _plain(ui.startup("0.14.0", provider=prov))
    assert "base_url=h" not in out
    assert "deepseek-v4-flash" in out


def test_describe_short_form():
    from psyclaw.providers.base import Provider

    class _P(Provider):
        name = "deepseek"

        def __init__(self):
            self.model = "deepseek-v4-flash"
            self.base_url = "https://api.deepseek.com"
            self.api_key = "sk-xxx"

        def chat(self, messages, system=""):
            return iter([])

    d = _P().describe_short()
    assert "deepseek" in d and "deepseek-v4-flash" in d
    assert "base_url" not in d and "https://" not in d     # 短形态不带冗长 URL
