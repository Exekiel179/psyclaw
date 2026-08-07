#!/usr/bin/env python3
"""Structure + visual regression verifier for a DOCX artifact."""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from psyclaw.output.docx_contract import inspect_docx
from psyclaw.output.docx_visual import compare_visual_manifests, render_docx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("docx")
    parser.add_argument("--baseline", help="existing visual_manifest.json")
    parser.add_argument("--output-dir", help="keep render intermediates here")
    args = parser.parse_args()

    contract = inspect_docx(args.docx)
    if not contract["ok"]:
        print(json.dumps(contract, ensure_ascii=False, indent=2))
        return 1
    if args.output_dir:
        rendered = render_docx(args.docx, args.output_dir)
    else:
        with tempfile.TemporaryDirectory(prefix="psyclaw_docx_verify_") as td:
            rendered = render_docx(args.docx, td)
            if args.baseline and rendered.get("ok"):
                rendered["comparison"] = compare_visual_manifests(
                    rendered, json.loads(Path(args.baseline).read_text(encoding="utf-8")))
    if args.baseline and args.output_dir and rendered.get("ok"):
        rendered["comparison"] = compare_visual_manifests(
            rendered, json.loads(Path(args.baseline).read_text(encoding="utf-8")))
    print(json.dumps({"contract": contract, "render": rendered}, ensure_ascii=False, indent=2))
    return 0 if rendered.get("ok") and rendered.get("comparison", {"ok": True})["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
