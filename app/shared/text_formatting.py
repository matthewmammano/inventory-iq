"""Small text-formatting helpers shared by Python code and Jinja templates."""


def pluralize(word: str, count: int) -> str:
    """Return `word` unchanged for a count of 1, otherwise with a trailing 's'."""
    return word if count == 1 else f"{word}s"
