"""feat-103:检索计划包(源自浏览器桥接文献综述教学文档)。"""

from __future__ import annotations

import json

from psyclaw.psych.litplan import (
    build_boolean_query,
    build_search_plan,
    default_criteria,
    render_search_plan_md,
    write_search_plan,
)


def test_boolean_query_with_synonyms():
    q = build_boolean_query("心理电子沙盘", ["心理电子沙盘", "虚拟沙盘"],
                            ["digital sandtray", "virtual sandplay"])
    assert '"心理电子沙盘" OR "虚拟沙盘"' in q["query_zh"]
    assert '"digital sandtray" OR "virtual sandplay"' in q["query_en"]
    assert " AND " in q["query_zh"] and " AND " in q["query_en"]


def test_boolean_query_template_without_synonyms():
    q = build_boolean_query("正念干预")
    assert "正念干预" in q["query_zh"] and "<同义词1>" in q["query_zh"]


def test_default_criteria_numbered_and_declared():
    c = default_criteria("电子沙盘")
    assert len(c["inclusion"]) >= 3 and len(c["exclusion"]) >= 3
    assert "检索前声明" in c["note"] and "不改标准" in c["note"]


def test_build_plan_offline_no_provider():
    """无 provider 走模板骨架,绝不阻塞(离线可用)。"""
    plan = build_search_plan("心理电子沙盘", provider=None, n_target=15)
    assert plan["llm_customized"] is False
    assert len(plan["bridge_steps"]) == 5
    assert "psyclaw lit" in plan["public_api"]
    assert "累计 15 条" in plan["bridge_steps"][3]["prompt"]


def test_bridge_steps_carry_discipline():
    """桥接提示词内嵌纪律:不猜测/未显示标注/长输出写文件。"""
    plan = build_search_plan("x")
    prompts = " ".join(s["prompt"] for s in plan["bridge_steps"])
    assert "不要猜测" in prompts and "未显示" in prompts
    assert "写到文件" in prompts or "写文件" in prompts


def test_render_md_sections():
    md = render_search_plan_md(build_search_plan("电子沙盘", n_target=20))
    for sec in ("布尔检索式", "公开学术 API", "浏览器桥接", "纳入 / 排除标准",
                "一次一件事", "psyclaw lit"):
        assert sec in md, sec


def test_write_search_plan_files(tmp_path):
    res = write_search_plan("电子沙盘", project_dir=str(tmp_path), n_target=12)
    plan_md = (tmp_path / "notes" / "search_plan.md").read_text(encoding="utf-8")
    assert "检索计划 — 电子沙盘" in plan_md and "累计 12 条" in plan_md
    crit = json.loads((tmp_path / "notes" / "screening_criteria.json")
                      .read_text(encoding="utf-8"))
    assert crit["topic"] == "电子沙盘" and crit["inclusion"]


class _FakeProvider:
    api_key = "k"
    name = "fake"

    def chat(self, msgs, system=""):
        yield json.dumps({
            "synonyms_zh": ["心理电子沙盘", "数字沙盘"],
            "synonyms_en": ["digital sandtray"],
            "inclusion": ["与心理干预相关"],
            "exclusion": ["纯工程展示"],
        }, ensure_ascii=False)


def test_llm_customization_used_when_available():
    plan = build_search_plan("心理电子沙盘", provider=_FakeProvider())
    assert plan["llm_customized"] is True
    assert '"心理电子沙盘" OR "数字沙盘"' in plan["query"]["query_zh"]
    assert plan["criteria"]["inclusion"] == ["与心理干预相关"]


class _BoomProvider:
    api_key = "k"
    name = "boom"

    def chat(self, msgs, system=""):
        raise RuntimeError("炸")


def test_llm_failure_falls_back_to_template():
    plan = build_search_plan("正念", provider=_BoomProvider())
    assert plan["llm_customized"] is False and "<同义词1>" in plan["query"]["query_zh"]
