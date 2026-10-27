"""Response models for the admin help articles."""

from pydantic import BaseModel

from .articles import HelpIndex
from .schema import HelpArticle


class HelpArticleSummaryResponse(BaseModel):
    """One article as the help index lists it, with the text its search box matches on."""

    id: str
    title: str
    summary: str
    tags: list[str]
    search_text: str

    @classmethod
    def of(cls, article: HelpArticle) -> "HelpArticleSummaryResponse":
        return cls(
            id=article.id,
            title=article.title,
            summary=article.summary,
            tags=list(article.tags),
            search_text=article.search_text,
        )


class HelpIndexResponse(BaseModel):
    """Every help article plus the tag filters the index offers."""

    articles: list[HelpArticleSummaryResponse]
    tags: list[str]

    @classmethod
    def of(cls, index: HelpIndex) -> "HelpIndexResponse":
        return cls(articles=[HelpArticleSummaryResponse.of(article) for article in index.articles], tags=list(index.tags))


class HelpArticleResponse(BaseModel):
    """One article, its body already rendered to the narrow HTML the help renderer allows."""

    id: str
    title: str
    summary: str
    tags: list[str]
    body_html: str

    @classmethod
    def of(cls, article: HelpArticle) -> "HelpArticleResponse":
        return cls(
            id=article.id,
            title=article.title,
            summary=article.summary,
            tags=list(article.tags),
            body_html=article.body_html,
        )
