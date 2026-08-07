from pathlib import Path

from psyclaw.handoff import write_handoff
from psyclaw.materials import convert_video_url


def test_write_handoff_is_replayable(tmp_path: Path):
    result = write_handoff(tmp_path, goal="Finish the study", completed=["Convert sources"],
                           next_steps=["Review claims"], generated_at="2026-08-07T00:00:00+00:00")
    assert result["ok"] is True
    assert "## Next Steps" in (tmp_path / "HANDOFF.md").read_text(encoding="utf-8")
    assert result["sidecar"].endswith("HANDOFF.md.json")


def test_video_converter_rejects_non_url_without_network():
    result = convert_video_url("bilibili-video")
    assert result["ok"] is False and result["status"] == "invalid_url"
