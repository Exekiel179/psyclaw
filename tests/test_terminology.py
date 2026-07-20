"""Prevent deprecated translated jargon from returning to active user-facing copy."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".py", ".md", ".json", ".yaml"}
FORBIDDEN_TERMS = (
    "".join(chr(code) for code in (27133, 20301)),
    "".join(chr(code) for code in (38376, 31105)),
)


def test_active_copy_avoids_deprecated_translated_jargon():
    targets = [ROOT / "psyclaw", ROOT / "docs"]
    files = [ROOT / "README.md", ROOT / "dev" / "docs" / "DESIGN.md"]
    for target in targets:
        files.extend(
            path for path in target.rglob("*")
            if path.is_file() and path.suffix in TEXT_SUFFIXES
        )

    violations = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for term in FORBIDDEN_TERMS:
            if term in text:
                violations.append(f"{path.relative_to(ROOT)}: {term}")

    assert not violations, "Deprecated terminology found:\n" + "\n".join(violations)
