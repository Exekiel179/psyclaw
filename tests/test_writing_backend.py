"""writing_backend 测试 — 双路后端(ARS插件/内置)探测、提示与产出。

运行: python -m pytest tests/test_writing_backend.py -q
原则:
  - detect_backend() 按 env var → 文件路径 → 回落 builtin 正确分支。
  - get_write_task() ARS 提示比内置提示更丰富（含双语摘要/JARS 章节列表）。
  - write_abstract() 解析结构正确；builtin 降级不调用 LLM。
  - write_paper() 调用 LLM，写 outputs/report.md，ARS 后端额外写 bilingual abstract。
  - 插件缺失时降级可用，不抛异常。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.output.writing_backend import (  # noqa: E402
    BACKEND_ARS,
    BACKEND_BUILTIN,
    _ars_plugin_paths,
    _ars_plugin_installed,
    _ars_write_task,
    _builtin_write_task,
    _extract_abstract_builtin,
    _parse_abstract_output,
    detect_backend,
    get_write_task,
    run_jars_check,
    write_abstract,
    write_paper,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

class _MockProvider:
    name = "mock"

    def __init__(self, response: str = "draft content"):
        self._response = response

    def chat(self, messages, system=""):
        yield self._response


def _make_project() -> Path:
    tmp = Path(tempfile.mkdtemp())
    for sub in ("outputs", "notes", "logs"):
        (tmp / sub).mkdir(parents=True, exist_ok=True)
    return tmp


# ---------------------------------------------------------------------------
# 插件路径探测
# ---------------------------------------------------------------------------

def test_plugin_paths_nonempty():
    paths = _ars_plugin_paths()
    assert len(paths) >= 2  # at minimum home-based paths


def test_plugin_paths_include_home():
    home = Path.home()
    paths = _ars_plugin_paths()
    assert any(str(home) in str(p) for p in paths)


def test_plugin_paths_include_appdata_on_windows():
    if "APPDATA" not in os.environ:
        return  # skip on non-Windows
    appdata = Path(os.environ["APPDATA"])
    paths = _ars_plugin_paths()
    assert any(str(appdata).lower() in str(p).lower() for p in paths)


def test_plugin_installed_false_when_no_dir(tmp_path):
    fake_paths = [tmp_path / "nonexistent"]
    with patch("psyclaw.output.writing_backend._ars_plugin_paths", return_value=fake_paths):
        assert _ars_plugin_installed() is False


def test_plugin_installed_true_when_dir_exists(tmp_path):
    plugin_dir = tmp_path / "academic-research-skills"
    plugin_dir.mkdir()
    with patch("psyclaw.output.writing_backend._ars_plugin_paths", return_value=[plugin_dir]):
        assert _ars_plugin_installed() is True


# ---------------------------------------------------------------------------
# detect_backend — env var 优先级
# ---------------------------------------------------------------------------

def test_detect_builtin_by_default_when_no_plugin(tmp_path):
    fake = [tmp_path / "no-plugin"]
    with patch("psyclaw.output.writing_backend._ars_plugin_paths", return_value=fake), \
         patch.dict(os.environ, {}, clear=False):
        os.environ.pop("PSYCLAW_ARS_BACKEND", None)
        result = detect_backend()
    assert result == BACKEND_BUILTIN


def test_detect_ars_when_env_plugin(tmp_path):
    with patch.dict(os.environ, {"PSYCLAW_ARS_BACKEND": "plugin"}):
        assert detect_backend() == BACKEND_ARS


def test_detect_ars_when_env_ars(tmp_path):
    with patch.dict(os.environ, {"PSYCLAW_ARS_BACKEND": "ars"}):
        assert detect_backend() == BACKEND_ARS


def test_detect_builtin_when_env_builtin():
    with patch.dict(os.environ, {"PSYCLAW_ARS_BACKEND": "builtin"}):
        assert detect_backend() == BACKEND_BUILTIN


def test_detect_builtin_when_env_simple():
    with patch.dict(os.environ, {"PSYCLAW_ARS_BACKEND": "simple"}):
        assert detect_backend() == BACKEND_BUILTIN


def test_detect_ars_when_plugin_dir_exists(tmp_path):
    plugin_dir = tmp_path / "academic-research-skills"
    plugin_dir.mkdir()
    with patch("psyclaw.output.writing_backend._ars_plugin_paths", return_value=[plugin_dir]), \
         patch.dict(os.environ, {}, clear=False):
        os.environ.pop("PSYCLAW_ARS_BACKEND", None)
        result = detect_backend()
    assert result == BACKEND_ARS


def test_env_overrides_plugin_presence(tmp_path):
    plugin_dir = tmp_path / "academic-research-skills"
    plugin_dir.mkdir()
    with patch("psyclaw.output.writing_backend._ars_plugin_paths", return_value=[plugin_dir]), \
         patch.dict(os.environ, {"PSYCLAW_ARS_BACKEND": "builtin"}):
        assert detect_backend() == BACKEND_BUILTIN


# ---------------------------------------------------------------------------
# 写作任务提示内容
# ---------------------------------------------------------------------------

def test_builtin_task_nonempty():
    task = _builtin_write_task()
    assert len(task) > 50
    assert "APA" in task or "JARS" in task


def test_ars_task_richer_than_builtin():
    ars = _ars_write_task()
    builtin = _builtin_write_task()
    assert len(ars) > len(builtin)


def test_ars_task_contains_bilingual():
    task = _ars_write_task()
    assert "中文摘要" in task or "双语" in task


def test_ars_task_contains_jars_sections():
    task = _ars_write_task()
    for section in ("引言", "方法", "结果", "讨论"):
        assert section in task


def test_ars_task_contains_goal():
    task = _ars_write_task("焦虑与学业成绩")
    assert "焦虑与学业成绩" in task


def test_ars_task_no_goal():
    task = _ars_write_task("")
    assert "研究目标:" not in task


def test_get_write_task_builtin():
    task = get_write_task(BACKEND_BUILTIN)
    assert task == _builtin_write_task()


def test_get_write_task_ars():
    task = get_write_task(BACKEND_ARS, "测试目标")
    assert "测试目标" in task
    assert len(task) > len(_builtin_write_task())


def test_ars_task_academic_integrity_rules():
    task = _ars_write_task()
    assert "95% CI" in task or "95%CI" in task
    assert "编造" in task


# ---------------------------------------------------------------------------
# _extract_abstract_builtin — 从草稿切割摘要段
# ---------------------------------------------------------------------------

DRAFT_WITH_ABSTRACT = """\
# Title

## Abstract
This study investigated the relationship between anxiety and academic achievement.
Participants (N=120) completed standardized measures.
Results showed a significant negative correlation.

## 方法
...
"""

DRAFT_ZH_ABSTRACT = """\
# 研究标题

## 摘要
本研究考察了焦虑与学业成绩的关系。

## 方法
...
"""


def test_extract_abstract_from_english_section():
    result = _extract_abstract_builtin(DRAFT_WITH_ABSTRACT)
    assert "anxiety" in result["en"].lower()
    assert result["zh"] == ""
    assert result["keywords_en"] == []


def test_extract_abstract_from_zh_section():
    result = _extract_abstract_builtin(DRAFT_ZH_ABSTRACT)
    assert "焦虑" in result["en"]


def test_extract_abstract_empty_when_no_section():
    result = _extract_abstract_builtin("# 标题\n\n正文内容")
    assert result["en"] == ""


# ---------------------------------------------------------------------------
# _parse_abstract_output — LLM 输出解析
# ---------------------------------------------------------------------------

MOCK_ABSTRACT_OUTPUT = """\
## Abstract
This study investigated anxiety and academic performance among 120 college students.
Results indicated a significant negative correlation (*r* = -.42, *p* < .001).

## 中文摘要
本研究考察了焦虑与学业成绩的关系（N=120）。结果显示显著负相关。

**Keywords:** anxiety; academic performance; college students; correlation; stress

**关键词：** 焦虑; 学业成绩; 大学生; 相关; 压力
"""


def test_parse_abstract_en():
    result = _parse_abstract_output(MOCK_ABSTRACT_OUTPUT)
    assert "anxiety" in result["en"].lower()
    assert "相关" in result["zh"]


def test_parse_abstract_keywords_en():
    result = _parse_abstract_output(MOCK_ABSTRACT_OUTPUT)
    assert "anxiety" in result["keywords_en"]
    assert len(result["keywords_en"]) == 5


def test_parse_abstract_keywords_zh():
    result = _parse_abstract_output(MOCK_ABSTRACT_OUTPUT)
    assert "焦虑" in result["keywords_zh"]
    assert len(result["keywords_zh"]) == 5


def test_parse_abstract_raw_preserved():
    result = _parse_abstract_output(MOCK_ABSTRACT_OUTPUT)
    assert result["raw"] == MOCK_ABSTRACT_OUTPUT


def test_parse_abstract_missing_sections():
    result = _parse_abstract_output("没有摘要的文本")
    assert result["en"] == ""
    assert result["zh"] == ""
    assert result["keywords_en"] == []


# ---------------------------------------------------------------------------
# write_abstract — 分 bilingual=True/False 两路
# ---------------------------------------------------------------------------

def test_write_abstract_bilingual_false_no_llm_call():
    provider = _MockProvider("should not be called")
    draft = DRAFT_WITH_ABSTRACT
    result = write_abstract(draft, provider, bilingual=False)
    assert "en" in result
    assert result["zh"] == ""


def test_write_abstract_bilingual_true_calls_provider():
    provider = _MockProvider(MOCK_ABSTRACT_OUTPUT)
    result = write_abstract(DRAFT_WITH_ABSTRACT, provider, bilingual=True)
    assert "en" in result
    assert result["raw"] is not None


def test_write_abstract_provider_error_returns_error_key():
    class _BrokenProvider:
        name = "broken"
        def chat(self, messages, system=""):
            raise RuntimeError("LLM 故障")

    result = write_abstract("draft text", _BrokenProvider(), bilingual=True)
    assert "raw" in result
    assert "生成失败" in result["raw"] or result["en"] == ""


# ---------------------------------------------------------------------------
# run_jars_check — 集成测试（不依赖 LLM）
# ---------------------------------------------------------------------------

MINIMAL_DRAFT = """\
# 标题
## Abstract
This study examined anxiety.
## 方法
Participants (N=50) were recruited.
Missing data: none.
Exclusions: 3 participants excluded.
## 结果
Results showed *t*(48) = 2.1, *p* = .04, Cohen's *d* = 0.60.
## 讨论
Limitations include convenience sampling.
"""


def test_run_jars_check_returns_dict(tmp_path):
    draft_path = tmp_path / "report.md"
    draft_path.write_text(MINIMAL_DRAFT, encoding="utf-8")
    result = run_jars_check(draft_path)
    assert isinstance(result, dict)
    assert "passed" in result


def test_run_jars_check_missing_file_returns_error(tmp_path):
    result = run_jars_check(tmp_path / "nonexistent.md")
    assert "error" in result
    assert result["passed"] is False


# ---------------------------------------------------------------------------
# write_paper — 主写作函数（stub provider）
# ---------------------------------------------------------------------------

def test_write_paper_builtin_creates_report(tmp_path):
    proj = _make_project()
    provider = _MockProvider("# 论文草稿\n正文内容")
    draft, meta = write_paper("测试目标", "上下文", provider, proj,
                              backend=BACKEND_BUILTIN, run_jars=False)
    assert "论文草稿" in draft
    assert (proj / "outputs" / "report.md").exists()
    assert meta["backend"] == BACKEND_BUILTIN


def test_write_paper_ars_creates_report_and_abstract(tmp_path):
    proj = _make_project()
    provider = _MockProvider(MOCK_ABSTRACT_OUTPUT)
    draft, meta = write_paper("焦虑研究", "上下文", provider, proj,
                              backend=BACKEND_ARS, run_jars=False)
    assert (proj / "outputs" / "report.md").exists()
    assert meta["backend"] == BACKEND_ARS


def test_write_paper_ars_writes_bilingual_abstract(tmp_path):
    proj = _make_project()
    provider = _MockProvider(MOCK_ABSTRACT_OUTPUT)
    _, meta = write_paper("焦虑研究", "上下文", provider, proj,
                          backend=BACKEND_ARS, run_jars=False)
    abs_path = proj / "notes" / "abstract_bilingual.md"
    assert abs_path.exists()
    content = abs_path.read_text(encoding="utf-8")
    assert "Abstract" in content
    assert "中文摘要" in content


def test_write_paper_run_jars_writes_json(tmp_path):
    proj = _make_project()
    provider = _MockProvider(MINIMAL_DRAFT)
    _, meta = write_paper("测试", "ctx", provider, proj,
                          backend=BACKEND_BUILTIN, run_jars=True)
    jars_path = proj / "notes" / "jars_check.json"
    assert jars_path.exists()
    data = json.loads(jars_path.read_text())
    assert "passed" in data
    assert meta["jars"] is not None


def test_write_paper_empty_provider_returns_empty(tmp_path):
    proj = _make_project()
    provider = _MockProvider("")
    draft, meta = write_paper("目标", "ctx", provider, proj,
                              backend=BACKEND_BUILTIN, run_jars=False)
    assert draft.strip() == ""


def test_write_paper_auto_detect_backend_respects_env():
    proj = _make_project()
    provider = _MockProvider("draft")
    with patch.dict(os.environ, {"PSYCLAW_ARS_BACKEND": "builtin"}):
        _, meta = write_paper("目标", "ctx", provider, proj,
                              backend=None, run_jars=False)
    assert meta["backend"] == BACKEND_BUILTIN


def test_write_paper_ars_meta_contains_abstract_key(tmp_path):
    proj = _make_project()
    provider = _MockProvider(MOCK_ABSTRACT_OUTPUT)
    _, meta = write_paper("目标", "ctx", provider, proj,
                          backend=BACKEND_ARS, run_jars=False)
    assert "abstract" in meta


def test_write_paper_builtin_meta_abstract_is_none(tmp_path):
    proj = _make_project()
    provider = _MockProvider("草稿内容")
    _, meta = write_paper("目标", "ctx", provider, proj,
                          backend=BACKEND_BUILTIN, run_jars=False)
    assert meta["abstract"] is None


# ---------------------------------------------------------------------------
# 自包含 runner(无 pytest 也可跑: python tests/test_writing_backend.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import inspect
    import tempfile

    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in fns:
        sig = inspect.signature(fn)
        try:
            if "tmp_path" in sig.parameters:
                with tempfile.TemporaryDirectory() as _td:
                    fn(tmp_path=Path(_td))
            else:
                fn()
            print(f"  ✓ {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  ✗ {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ✗ {name}: [ERROR] {type(exc).__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
