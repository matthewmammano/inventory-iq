"""Ban em-dashes and prose double hyphens in text files (see CLAUDE.md comment rules).

Invoked by the check-dashes pre-commit hook, which selects which files to scan.
"""

import re
import sys
from pathlib import Path

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
BANNED_CHARS = {EM_DASH: "em-dash", EN_DASH: "en-dash"}
# A prose dash stands alone between spaces; "--flag" and "--custom-property" do not.
PROSE_DOUBLE_HYPHEN = re.compile(r"(?<=\s)--(?=\s|$)")
MAX_EXCERPT = 100


def _violations(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    found: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        labels = [label for char, label in BANNED_CHARS.items() if char in line]
        if PROSE_DOUBLE_HYPHEN.search(line):
            labels.append("prose double hyphen")
        found.extend(f"{path}:{number}: {label}: {line.strip()[:MAX_EXCERPT]}" for label in labels)
    return found


def main(paths: list[str]) -> int:
    """Print every violation in the given files and return a process exit code."""
    found = [violation for name in paths if (path := Path(name)).is_file() for violation in _violations(path)]
    for violation in found:
        print(violation)
    if found:
        print(f"{len(found)} violation(s). Use a period, semicolon, or plain '-'.")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
