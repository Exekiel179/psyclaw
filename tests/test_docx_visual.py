from psyclaw.output.docx_visual import compare_visual_manifests


def test_visual_manifest_comparison_reports_changed_pages():
    baseline = {"coverage": "full", "pages": [{"name": "page-1.png", "sha256": "a"}]}
    current = {"coverage": "full", "pages": [{"name": "page-1.png", "sha256": "b"}]}
    result = compare_visual_manifests(current, baseline)
    assert result["ok"] is False and result["changed"] == ["page-1.png"]


def test_visual_manifest_comparison_accepts_identical_key_pages():
    manifest = {"coverage": "first_page", "pages": [{"name": "doc.png", "sha256": "a"}]}
    assert compare_visual_manifests(manifest, manifest)["ok"] is True
