#!/usr/bin/env python3
"""Build a small DOCX fixture that exercises APA three-line tables."""
from __future__ import annotations

import argparse
from pathlib import Path

from psyclaw.output.apa7 import APA7Document
from psyclaw.output.docx_contract import assert_docx_contract


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", nargs="?", default="outputs/three-line-table-test.docx")
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    doc = APA7Document(
        title="APA 三线表生成测试",
        authors="PsyClaw DOCX regression fixture",
        affiliation="Local verification",
    )
    doc.add_heading("结果", 1)
    doc.add_paragraph("以下表格用于检查边框、固定列宽、中文换行与跨页稳定性。")
    doc.add_stat_table(
        "Table 1\n描述性统计",
        ["变量", "n", "M", "SD", "95% CI"],
        [
            ["抑郁症状", "128", "14.20", "3.40", "[13.60, 14.80]"],
            ["焦虑症状", "128", "11.10", "2.90", "[10.59, 11.61]"],
            ["生活满意度（较长的中文变量名称，用于测试自动换行）", "128", "24.80", "5.10", "[23.90, 25.70]"],
        ],
    )
    doc.add_stat_table(
        "Table 2\n相关矩阵",
        ["变量", "1", "2", "3"],
        [
            ["1. 抑郁", "—", "", ""],
            ["2. 焦虑", ".45", "—", ""],
            ["3. 满意度", "-.31", "-.27", "—"],
        ],
    )
    doc.add_stat_table("Table 3\n仅表头边界情况", ["变量", "结果"], [])

    doc.to_docx(output)
    result = assert_docx_contract(output)
    print(f"generated={output.resolve()}")
    print(f"sha256={result['sha256']}")
    print(f"tables={result['tables']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
