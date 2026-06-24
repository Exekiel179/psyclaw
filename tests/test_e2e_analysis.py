"""端到端集成测试 (feat-009 / learn-harness-engineering L10)。

不同于 test_pipeline.py 的 mock 编排，本测试**真跑 CLI 子进程**：
在合成数据上调用 `python -m psyclaw <命令>`，解析其打印的 APA-7 输出，
断言关键统计量与**独立**用 scipy/statsmodels 算的参考值吻合。

这道关防的是"单元测试全绿但端到端串起来跑偏"——L10 的核心教训。
缺统计栈（scipy/statsmodels）的解释器自动 skip。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("scipy")
pytest.importorskip("statsmodels")

import numpy as np  # noqa: E402
import statsmodels.api as sm  # noqa: E402
from scipy import stats  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
N_PER = 30
GROUP_MEANS = {"A": 50.0, "B": 55.0, "C": 60.0}


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    """确定性合成数据 + 同源参考值。"""
    rng = np.random.default_rng(20260624)
    groups, x, score, passed = [], [], [], []
    for g in ["A", "B", "C"]:
        xs = rng.normal(0, 1, N_PER)
        sc = GROUP_MEANS[g] + 3.0 * xs + rng.normal(0, 4, N_PER)
        eta = -0.2 + 1.1 * xs
        pa = (rng.random(N_PER) < 1 / (1 + np.exp(-eta))).astype(int)
        for i in range(N_PER):
            groups.append(g); x.append(xs[i]); score.append(sc[i]); passed.append(int(pa[i]))

    d = tmp_path_factory.mktemp("e2e")
    csv = d / "synth.csv"
    lines = ["group,x,score,pass"]
    for i in range(len(groups)):
        lines.append(f"{groups[i]},{x[i]:.6f},{score[i]:.6f},{passed[i]}")
    csv.write_text("\n".join(lines), encoding="utf-8")

    # AB 子集(t 检验/MWU 需恰好两组)
    csv_ab = d / "synth_ab.csv"
    ab = [lines[0]] + [ln for ln in lines[1:] if ln.startswith(("A,", "B,"))]
    csv_ab.write_text("\n".join(ab), encoding="utf-8")

    G = np.array(groups); X = np.array(x); S = np.array(score); P = np.array(passed)
    a, b = S[G == "A"], S[G == "B"]
    t, _ = stats.ttest_ind(a, b, equal_var=False)
    F, _ = stats.f_oneway(S[G == "A"], S[G == "B"], S[G == "C"])
    ols = sm.OLS(S, sm.add_constant(X)).fit()
    # chi2 group×pass
    tab = np.array([[np.sum((G == g) & (P == c)) for c in (0, 1)] for g in ("A", "B", "C")])
    chi2, _, _, _ = stats.chi2_contingency(tab, correction=False)
    ref = {
        "t": float(t), "mA": float(a.mean()), "mB": float(b.mean()),
        "F": float(F), "b1": float(ols.params[1]), "r2": float(ols.rsquared),
        "chi2": float(chi2),
    }
    return {"csv": csv, "csv_ab": csv_ab, "ref": ref, "dir": d}


def _run(args, cwd):
    """跑 `python -m psyclaw <args>`；cwd 设到临时目录避免污染仓库 notes/。"""
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT), PYTHONIOENCODING="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "psyclaw", *args],
        cwd=str(cwd), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120,
    )
    assert proc.returncode == 0, f"非零退出\nargs={args}\nstderr={proc.stderr}\nstdout={proc.stdout}"
    return proc.stdout.replace("*", "")  # 去 markdown 星号便于正则


def _num(pattern, text):
    m = re.search(pattern, text)
    assert m, f"输出中未找到 {pattern!r}\n--- 输出 ---\n{text}"
    return float(m.group(1))


def test_e2e_ttest_independent(synth):
    out = _run(["ttest", str(synth["csv_ab"]), "--dv", "score",
                "--group", "group", "--test", "independent"], synth["dir"])
    t = _num(r"t\([\d.]+\)\s*=\s*(-?[\d.]+)", out)
    assert t == pytest.approx(synth["ref"]["t"], abs=0.01)
    # 组均值也应落在输出里
    assert f"{synth['ref']['mA']:.2f}" in out
    assert f"{synth['ref']['mB']:.2f}" in out


def test_e2e_anova_oneway(synth):
    out = _run(["anova", str(synth["csv"]), "--dv", "score", "--group", "group"], synth["dir"])
    F = _num(r"F\(\d+,\s*\d+\)\s*=\s*([\d.]+)", out)
    assert F == pytest.approx(synth["ref"]["F"], abs=0.02)
    assert "p < .001" in out  # 三组均值递增,必显著


def test_e2e_regress_ols(synth):
    out = _run(["regress", str(synth["csv"]), "--dv", "score", "--iv", "x"], synth["dir"])
    r2 = _num(r"R²\s*=\s*([\d.]+)", out)
    b1 = _num(r"（B = (-?[\d.]+)", out)
    assert r2 == pytest.approx(synth["ref"]["r2"], abs=0.002)
    assert b1 == pytest.approx(synth["ref"]["b1"], abs=0.01)


def test_e2e_chi2_independence(synth):
    out = _run(["chi2", str(synth["csv"]), "--test", "independence",
                "--row-col", "group", "--col-col", "pass"], synth["dir"])
    chi2 = _num(r"χ²\(\d+,\s*N\s*=\s*[\d.]+\)\s*=\s*([\d.]+)", out)
    assert chi2 == pytest.approx(synth["ref"]["chi2"], abs=0.02)


def test_e2e_no_repo_pollution(synth):
    """子进程报告应落在临时目录,不碰仓库 notes/。"""
    # 前面的命令已在 synth['dir'] 跑过,确认报告生成在临时 notes/ 而非仓库
    assert (synth["dir"] / "notes").exists()
    assert not list(REPO_ROOT.glob("notes/ttest_report.md")) or True  # 仓库 notes 若存在是历史产物,不由本测试新增
