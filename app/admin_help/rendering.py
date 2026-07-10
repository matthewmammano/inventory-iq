"""Small safe renderer for admin help article text.

Supports a deliberately narrow markdown subset: headings (##/###), paragraphs,
lists (-/1.), a callout line (> ), and three inline styles (**bold**, `code`,
[text](url)). Everything else is escaped literally rather than silently dropped.
"""

import re

from markupsafe import Markup, escape

_INLINE_TOKEN = re.compile(r"\*\*(?P<bold>[^*]+)\*\*|`(?P<code>[^`]+)`|\[(?P<text>[^\]]+)\]\((?P<url>[^)]+)\)")


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
            html.append(f"<h{heading_level}>{_render_inline(heading_text)}</h{heading_level}>")
            continue
        callout_text = _callout_text(line)
        if callout_text is not None:
            _close_paragraph(html, paragraph)
            list_tag = _close_list(html, list_tag)
            html.append(f'<div class="alert info">{_render_inline(callout_text)}</div>')
            continue
        list_item = _list_item(line)
        if list_item:
            next_list_tag, item_text = list_item
            _close_paragraph(html, paragraph)
            if list_tag != next_list_tag:
                list_tag = _close_list(html, list_tag)
                html.append(f"<{next_list_tag}>")
                list_tag = next_list_tag
            html.append(f"<li>{_render_inline(item_text)}</li>")
            continue
        list_tag = _close_list(html, list_tag)
        paragraph.append(line)

    _close_paragraph(html, paragraph)
    _close_list(html, list_tag)
    return "\n".join(html)


def _close_paragraph(html: list[str], paragraph: list[str]) -> None:
    if paragraph:
        html.append(f"<p>{_render_inline(' '.join(paragraph))}</p>")
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


def _callout_text(line: str) -> str | None:
    if line.startswith("> "):
        return line.removeprefix("> ").strip()
    return None


def _list_item(line: str) -> tuple[str, str] | None:
    if line.startswith("- "):
        return "ul", line.removeprefix("- ").strip()
    number, separator, text = line.partition(". ")
    if separator and number.isdigit():
        return "ol", text.strip()
    return None


def _render_inline(text: str) -> Markup:
    """Escape text, then re-enable bold and safe links within it."""
    pieces: list[Markup] = []
    last_end = 0
    for match in _INLINE_TOKEN.finditer(text):
        pieces.append(escape(text[last_end : match.start()]))
        if match.group("bold") is not None:
            pieces.append(Markup("<strong>{}</strong>").format(match.group("bold")))
        elif match.group("code") is not None:
            pieces.append(Markup("<code>{}</code>").format(match.group("code")))
        else:
            pieces.append(_render_link(match.group("text"), match.group("url")))
        last_end = match.end()
    pieces.append(escape(text[last_end:]))
    return Markup("").join(pieces)


def _render_link(text: str, url: str) -> Markup:
    if not _is_safe_url(url):
        return Markup("{} ({})").format(text, url)
    external_attrs = Markup(' target="_blank" rel="noopener noreferrer"') if url.startswith("https://") else Markup("")
    return Markup('<a class="text-link" href="{}"{}>{}</a>').format(url, external_attrs, text)


def _is_safe_url(url: str) -> bool:
    """Allow https links, absolute paths, and same-directory relative links (other article ids).

    Rejects any other scheme (javascript:, data:, mailto:, ...) by requiring no
    colon outside of the explicitly-allowed https:// prefix.
    """
    if url.startswith("https://") or url.startswith("/"):
        return True
    return ":" not in url
