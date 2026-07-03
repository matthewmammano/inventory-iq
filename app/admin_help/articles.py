"""File-backed admin help articles."""

from pathlib import Path

from app.admin_help.rendering import render_help_markdown
from app.admin_help.schema import HelpArticle, HelpArticleMetadata

ARTICLES_DIR = Path(__file__).with_name("articles")
FRONT_MATTER_DELIMITER = "---"


def list_help_articles() -> tuple[HelpArticle, ...]:
    articles = tuple(_load_article(path) for path in sorted(ARTICLES_DIR.glob("*.md")))
    return tuple(sorted(articles, key=lambda article: article.title.casefold()))


def get_help_article(article_id: str) -> HelpArticle | None:
    return next((article for article in list_help_articles() if article.id == article_id), None)


def list_help_tags(articles: tuple[HelpArticle, ...]) -> tuple[str, ...]:
    tags: list[str] = []
    seen: set[str] = set()
    for article in articles:
        for tag in article.tags:
            key = tag.casefold()
            if key not in seen:
                seen.add(key)
                tags.append(tag)
    return tuple(tags)


def _load_article(path: Path) -> HelpArticle:
    metadata, body_markdown = _split_article(path)
    return HelpArticle(
        **metadata.model_dump(),
        body_markdown=body_markdown,
        body_html=render_help_markdown(body_markdown),
    )


def _split_article(path: Path) -> tuple[HelpArticleMetadata, str]:
    text = path.read_text(encoding="utf-8").lstrip("\ufeff").strip()
    if not text.startswith(FRONT_MATTER_DELIMITER):
        raise ValueError(f"{path.name} must start with front matter.")
    _start, metadata_text, body_markdown = text.split(FRONT_MATTER_DELIMITER, 2)
    metadata = _parse_metadata(metadata_text)
    if metadata.id != path.stem:
        raise ValueError(f"{path.name} id must match filename.")
    return metadata, body_markdown.strip()


def _parse_metadata(metadata_text: str) -> HelpArticleMetadata:
    values: dict[str, object] = {}
    for raw_line in metadata_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        key, separator, value = line.partition(":")
        if not separator:
            raise ValueError(f"Invalid help article metadata line: {line}")
        clean_key = key.strip()
        clean_value = value.strip()
        values[clean_key] = tuple(tag.strip() for tag in clean_value.split(",")) if clean_key == "tags" else clean_value
    return HelpArticleMetadata.model_validate(values)
