"""JSON endpoints for the admin help articles."""

from http import HTTPStatus
from typing import Final

from apiflask import HTTPError
from loguru import logger

from app.admin_help.articles import get_help_article, load_help_index
from app.admin_help.response import HelpArticleResponse, HelpIndexResponse
from app.api.admin_access import admin_only
from app.api.blueprint import api_bp
from app.api.constants import AGENCY_ROUTE

HELP_ARTICLES_ROUTE: Final[str] = f"{AGENCY_ROUTE}/admin/help/articles"
ARTICLE_NOT_FOUND_MESSAGE: Final[str] = "That help article does not exist."


@api_bp.get(HELP_ARTICLES_ROUTE)
@api_bp.output(HelpIndexResponse)
@api_bp.doc(summary="List every help article and the tags they can be filtered by")
@admin_only
def list_help_index(agency_id: int) -> HelpIndexResponse:
    index = load_help_index()
    logger.debug("Help index read", extra={"agency_id": agency_id, "article_count": len(index.articles)})
    return HelpIndexResponse.of(index)


@api_bp.get(f"{HELP_ARTICLES_ROUTE}/<article_id>")
@api_bp.output(HelpArticleResponse)
@api_bp.doc(summary="Read one help article")
@admin_only
def read_help_article(agency_id: int, article_id: str) -> HelpArticleResponse:
    article = get_help_article(article_id)
    if article is None:
        logger.info("Help article not found", extra={"agency_id": agency_id, "article_id": article_id})
        raise HTTPError(HTTPStatus.NOT_FOUND, ARTICLE_NOT_FOUND_MESSAGE)
    return HelpArticleResponse.of(article)
