"""feat-160:new 建的分析文件夹带研究流程引导 README——打开即知怎么走。"""
from __future__ import annotations

from psyclaw.scaffold import create_analysis


def _readme(tmp_path, name="study", goal=""):
    create_analysis(name, goal=goal, base_dir=str(tmp_path))
    return (tmp_path / name / "README.md").read_text(encoding="utf-8")


def test_readme_created(tmp_path):
    create_analysis("s", base_dir=str(tmp_path))
    assert (tmp_path / "s" / "README.md").is_file()


def test_readme_has_mental_model(tmp_path):
    r = _readme(tmp_path)
    assert "chat" in r and "run" in r and "auto" in r     # 三种工作方式


def test_readme_literature_flow_accurate(tmp_path):
    """文献调研流程的命令必须是真命令(实走验证过的)。"""
    r = _readme(tmp_path)
    assert "lit --plan" in r
    assert "lit -s" in r or "lit --synthesize" in r
    assert "cite-check" in r


def test_readme_analysis_flow(tmp_path):
    r = _readme(tmp_path)
    assert "run analysis" in r
    assert "data/clean" in r


def test_readme_writing_flow(tmp_path):
    r = _readme(tmp_path)
    assert "export" in r and "docx" in r
    assert "check" in r


def test_readme_explains_dirs(tmp_path):
    r = _readme(tmp_path)
    for d in ("notes", "data/raw", "figures", "scripts", "outputs"):
        assert d in r


def test_readme_uses_analysis_name(tmp_path):
    r = _readme(tmp_path, name="拖延研究", goal="拖延与倦怠")
    assert "拖延研究" in r


def test_readme_no_fabricated_stat_command(tmp_path):
    """不得出现不存在的内置统计命令(统计外移铁律)。"""
    r = _readme(tmp_path)
    assert "psyclaw describe" not in r and "psyclaw ttest" not in r
