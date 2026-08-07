"""Machine-checkable contract for PsyClaw DOCX artifacts.

The exporter is deterministic, but a valid ZIP alone does not prove that the
document contains the requested research structure.  This module checks the
parts a downstream editor relies on without importing python-docx or Word.
"""
from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}


def _attr(node: ET.Element | None, name: str) -> str | None:
    return None if node is None else node.attrib.get(f"{{{W}}}{name}")


def inspect_docx(path: str | Path) -> dict:
    """Return structural diagnostics; malformed or incomplete files fail closed."""
    p = Path(path)
    errors: list[str] = []
    if not p.is_file():
        return {"ok": False, "errors": [f"文件不存在:{p}"], "sha256": None}
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    try:
        with zipfile.ZipFile(p) as z:
            names = set(z.namelist())
            required = {"[Content_Types].xml", "word/document.xml", "word/styles.xml",
                        "word/header1.xml", "word/_rels/document.xml.rels"}
            errors.extend(f"缺少 DOCX part:{n}" for n in sorted(required - names))
            root = ET.fromstring(z.read("word/document.xml")) if "word/document.xml" in names else None
            styles = ET.fromstring(z.read("word/styles.xml")) if "word/styles.xml" in names else None
            refs = root.findall(".//w:footnoteReference", NS) if root is not None else []
            if refs and "word/footnotes.xml" not in names:
                errors.append("存在脚注引用但缺少 word/footnotes.xml")
            footnotes = (ET.fromstring(z.read("word/footnotes.xml"))
                         if "word/footnotes.xml" in names else None)
    except (OSError, zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        return {"ok": False, "errors": [f"DOCX 读取失败:{exc}"], "sha256": digest}

    paragraphs = root.findall(".//w:body/w:p", NS) if root is not None else []
    texts = ["".join(t.text or "" for t in p.findall(".//w:t", NS)) for p in paragraphs]
    styles_seen = [_attr(p.find("./w:pPr/w:pStyle", NS), "val") for p in paragraphs]
    needed_styles = {"PCTitle", "PCH1", "PCH2", "PCH3", "PCBody", "PCRef"}
    defined = {_attr(s, "styleId") for s in styles.findall("./w:style", NS)} if styles is not None else set()
    errors.extend(f"缺少段落样式:{s}" for s in sorted(needed_styles - defined))
    if not any(s == "PCTitle" for s in styles_seen):
        errors.append("缺少标题页")
    if not any(s == "PCH1" for s in styles_seen):
        errors.append("缺少正文标题")
    table_count = len(root.findall(".//w:tbl", NS)) if root is not None else 0
    for idx, tbl in enumerate(root.findall(".//w:tbl", NS) if root is not None else [], 1):
        tbl_w = tbl.find("./w:tblPr/w:tblW", NS)
        layout = tbl.find("./w:tblPr/w:tblLayout", NS)
        grid = tbl.findall("./w:tblGrid/w:gridCol", NS)
        if _attr(tbl_w, "type") != "dxa" or _attr(layout, "type") != "fixed" or not grid:
            errors.append(f"表格 {idx} 缺少固定 DXA 几何")
        widths = [_attr(c, "w") for c in grid]
        for row in tbl.findall("./w:tr", NS):
            if row.find("./w:trPr/w:cantSplit", NS) is None:
                errors.append(f"表格 {idx} 存在可拆分行")
            cells = row.findall("./w:tc/w:tcPr/w:tcW", NS)
            if len(cells) != len(widths) or [_attr(c, "w") for c in cells] != widths:
                errors.append(f"表格 {idx} 单元格宽度与网格不一致")
    return {"ok": not errors, "errors": errors, "sha256": digest,
            "paragraphs": len(paragraphs), "tables": table_count,
            "footnotes": len(footnotes.findall("./w:footnote", NS)) if footnotes is not None else 0,
            "texts": texts}


def assert_docx_contract(path: str | Path) -> dict:
    result = inspect_docx(path)
    if not result["ok"]:
        raise ValueError("DOCX contract failed: " + "; ".join(result["errors"]))
    return result
