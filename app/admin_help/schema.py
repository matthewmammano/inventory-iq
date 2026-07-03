"""Typed admin help article models."""

import re

from pydantic import BaseModel, Field, field_validator

HELP_ARTICLE_ID_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


class HelpArticleMetadata(BaseModel):
    """Validated metadata loaded from a help article file."""

    id: str = Field(pattern=HELP_ARTICLE_ID_PATTERN)
    title: str = Field(min_length=1, max_length=90)
    summary: str = Field(min_length=1, max_length=180)
    tags: tuple[str, ...] = Field(min_length=1)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, tags: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(tag.strip() for tag in tags if tag.strip())
        if len(cleaned) != len({tag.casefold() for tag in cleaned}):
            raise ValueError("Article tags must be unique.")
        return cleaned


class HelpArticle(HelpArticleMetadata):
    """Rendered help article ready for templates and search."""

    body_markdown: str = Field(min_length=1)
    body_html: str = Field(min_length=1)

    @property
    def search_text(self) -> str:
        text = " ".join((self.title, self.summary, " ".join(self.tags), self.body_markdown))
        return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()

    @property
    def tag_keys(self) -> tuple[str, ...]:
        return tuple(tag.casefold() for tag in self.tags)
