"""Small file retention helpers for generated instance artifacts."""

from pathlib import Path


def keep_newest_files(directory: Path, pattern: str, max_files: int) -> None:
    """Delete oldest matching files so generated folders stay small."""
    files = sorted(
        (path for path in directory.glob(pattern) if path.is_file()),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    for path in files[max_files:]:
        path.unlink(missing_ok=True)
