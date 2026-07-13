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


def keep_newest_groups(directory: Path, anchor_pattern: str, max_groups: int) -> None:
    """Delete oldest file groups so generated folders stay small.

    A group is every file sharing the stem (name before the first `.`) of one
    `anchor_pattern` match -- e.g. a sent email's html/txt bodies plus its CSV
    attachments all share one stem and are kept or deleted together.
    """
    anchors = sorted(
        (path for path in directory.glob(anchor_pattern) if path.is_file()),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    for anchor in anchors[max_groups:]:
        stem = anchor.name.split(".", 1)[0]
        for sibling in directory.glob(f"{stem}*"):
            sibling.unlink(missing_ok=True)
