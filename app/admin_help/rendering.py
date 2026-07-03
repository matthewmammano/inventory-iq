"""Small safe renderer for admin help article text."""

from markupsafe import escape


def render_help_markdown(markdown: str) -> str:
    """Render the intentionally small help-article markdown subset."""
    html: list[str] = []
    paragraph: list[str] = []
    list_tag: str | None = None

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            _close_paragraph(html, paragraph)
            list_tag = _close_list(html, list_tag)
            continue
        heading_level = _heading_level(line)
        if heading_level:
            _close_paragraph(html, paragraph)
            list_tag = _close_list(html, list_tag)
            heading_text = line.removeprefix(f"{'#' * heading_level} ").strip()
            html.append(f"<h{heading_level}>{escape(heading_text)}</h{heading_level}>")
            continue
        list_item = _list_item(line)
        if list_item:
            next_list_tag, item_text = list_item
            _close_paragraph(html, paragraph)
            if list_tag != next_list_tag:
                list_tag = _close_list(html, list_tag)
                html.append(f"<{next_list_tag}>")
                list_tag = next_list_tag
            html.append(f"<li>{escape(item_text)}</li>")
            continue
        list_tag = _close_list(html, list_tag)
        paragraph.append(line)

    _close_paragraph(html, paragraph)
    _close_list(html, list_tag)
    return "\n".join(html)


def _close_paragraph(html: list[str], paragraph: list[str]) -> None:
    if paragraph:
        html.append(f"<p>{escape(' '.join(paragraph))}</p>")
        paragraph.clear()


def _close_list(html: list[str], list_tag: str | None) -> str | None:
    if list_tag:
        html.append(f"</{list_tag}>")
    return None


def _heading_level(line: str) -> int | None:
    if line.startswith("### "):
        return 3
    if line.startswith("## "):
        return 2
    return None


def _list_item(line: str) -> tuple[str, str] | None:
    if line.startswith("- "):
        return "ul", line.removeprefix("- ").strip()
    number, separator, text = line.partition(". ")
    if separator and number.isdigit():
        return "ol", text.strip()
    return None
