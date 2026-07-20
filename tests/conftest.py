"""测试夹具:把量表数据指向 tests/fixtures/,而非发行包内。

feat-186 起,psyclaw **不再内置量表库**(原 7 条 dass/phq/gad/tipi/rses/pss 定义
及其中文常模已移出发行包)——固定 7 条覆盖太窄,用户搜 MBI 只会得到「未收录」,
帮倒忙;而计分机器(反向计分/分量表求和/缺失处理/信度/伦理提示)是真有用的,
故保留,由用户在 `.psyclaw/scales/*.yaml` 里定义自己的量表来驱动。

但这些机器的测试原本拿内置量表当数据夹具。内容移出发行包后,夹具跟着移到这里:
机器的测试覆盖一条不少,发行包里却不再塞半吊子内容库。
"""
from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _scale_fixtures(monkeypatch):
    """把 scales/常模 的文件指针指向测试夹具(autouse:调用方无需改动)。

    只改文件路径,不碰任何解析/计分逻辑——被测的仍是真实实现。
    """
    from psyclaw.psych import scales
    monkeypatch.setattr(scales, "SCALES_FILE", FIXTURES / "scales.yaml", raising=False)
    monkeypatch.setattr(scales, "CN_NORMS_FILE", FIXTURES / "cn_norms.json",
                        raising=False)
    # 常模是模块级缓存,换文件后需失效,否则跨用例串味
    if hasattr(scales, "_CN_NORMS_CACHE"):
        monkeypatch.setattr(scales, "_CN_NORMS_CACHE", None, raising=False)
