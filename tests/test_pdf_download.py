"""feat-109:OA PDF 真下载 + 规范命名(goal 三样例实测三错的修复)。"""

from __future__ import annotations

import http.server
import threading

import pytest

from psyclaw.psych import litsearch as LS


# ---------------------------------------------------------------------------
# 命名
# ---------------------------------------------------------------------------

def test_pdf_filename_latin():
    p = {"title": "Effectiveness of online mindfulness-based interventions in "
                  "improving mental health outcomes",
         "authors": ["Marcel Spijkerman", "Wendy Pots"], "year": 2016}
    name = LS.pdf_filename(p)
    assert name == ("Spijkerman_2016_Effectiveness-of-online-mindfulness-"
                    "based-interventions-in-improving.pdf")


def test_pdf_filename_cjk():
    p = {"title": "认知行为疗法对青少年首发抑郁症患者的研究", "authors": ["苏巧荣", "王秀云"],
         "year": 2006}
    name = LS.pdf_filename(p)
    assert name.startswith("苏巧荣_2006_认知行为疗法对青少年首发抑郁症") and name.endswith(".pdf")


def test_pdf_filename_initial_last_token_uses_first():
    """「Chen Z.」式姓前名缩写后:末 token 是缩写时取首 token(实测 Z_2026 bug)。"""
    assert LS.pdf_filename({"title": "T x", "authors": ["Chen Z."], "year": 2026}
                           ).startswith("Chen_2026_")
    assert LS.pdf_filename({"title": "T x", "authors": ["Anna M. Friis"], "year": 2016}
                           ).startswith("Friis_2016_")
def test_pdf_filename_missing_fields():
    assert LS.pdf_filename({}) == "UnknownAuthor_n.d._untitled.pdf"


def test_pdf_filename_strips_bad_chars():
    p = {"title": 'A/B: "test" <x>|?*', "authors": ["Li, X."], "year": 2020}
    name = LS.pdf_filename(p)
    for ch in '\\/:*?"<>| ':
        assert ch not in name


def test_dedup_path_never_overwrites(tmp_path):
    fp = tmp_path / "a.pdf"
    fp.write_bytes(b"x")
    p2 = LS._dedup_path(tmp_path / "a.pdf")
    assert p2.name == "a-2.pdf"


# ---------------------------------------------------------------------------
# 下载(stdlib 假服务器)
# ---------------------------------------------------------------------------

@pytest.fixture()
def pdf_server():
    class _H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/real.pdf":
                body = b"%PDF-1.4 fake body " + b"x" * 100
                self.send_response(200)
            else:                                  # 落地页(HTML)
                body = b"<html>landing page</html>"
                self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_download_pdf_saves_named_file(tmp_path, pdf_server):
    paper = {"title": "A real study", "authors": ["Kim Lee"], "year": 2021}
    r = LS.download_pdf(f"{pdf_server}/real.pdf", str(tmp_path), paper)
    assert r["ok"] is True
    from pathlib import Path
    fp = Path(r["path"])
    assert fp.name == "Lee_2021_A-real-study.pdf" and fp.read_bytes().startswith(b"%PDF")


def test_download_rejects_landing_page_honestly(tmp_path, pdf_server):
    """落地页/HTML 绝不存成 .pdf——如实报失败(goal 实测错误①的反面守卫)。"""
    r = LS.download_pdf(f"{pdf_server}/landing", str(tmp_path), {"title": "x"})
    assert r["ok"] is False and "不是 PDF" in r["note"]
    assert not list(tmp_path.iterdir())


def test_fetch_and_save_downloads_oa_pdf(tmp_path, pdf_server, monkeypatch):
    paper = {"title": "T", "authors": ["A B"], "year": 2020, "doi": "10.1/x"}
    monkeypatch.setattr(LS, "get_fulltext", lambda p, out_dir=None: {
        "status": "oa_pdf", "pdf_url": f"{pdf_server}/real.pdf", "channel": "t"})
    res = LS.fetch_and_save(paper, str(tmp_path))
    assert res["downloaded"]["ok"] is True


def test_fetch_and_save_bare_doi_gets_metadata(tmp_path, pdf_server, monkeypatch):
    """裸 DOI 也能命好名:经 paper_from_doi 补题录(goal 实测错误③)。"""
    monkeypatch.setattr(LS, "get_fulltext", lambda p, out_dir=None: {
        "status": "oa_pdf", "pdf_url": f"{pdf_server}/real.pdf", "channel": "t"})
    monkeypatch.setattr(LS, "paper_from_doi", lambda d: {
        "title": "Named via DOI", "authors": ["Zhang San"], "year": 2019})
    res = LS.fetch_and_save({"doi": "10.9/z"}, str(tmp_path))
    from pathlib import Path
    assert Path(res["downloaded"]["path"]).name == "San_2019_Named-via-DOI.pdf"


def test_save_text_uses_same_naming(tmp_path):
    p = {"title": "Fulltext study", "authors": ["Wang Wu"], "year": 2018}
    fp = LS._save_text("正文" * 100, p, str(tmp_path))
    from pathlib import Path
    assert Path(fp).name == "Wu_2018_Fulltext-study.txt"