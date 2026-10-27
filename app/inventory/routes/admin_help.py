"""Admin help center routes."""

from typing import Any

from flask import abort, render_template

from app.admin_help.articles import get_help_article, load_help_index
from app.inventory import admin_bp as bp


@bp.route("/<int:agency_id>/admin-panel/help")
def admin_help(agency_id: int) -> Any:
    index = load_help_index()
    return render_template("admin_help.html", agency_id=agency_id, articles=index.articles, tags=index.tags, admin=True)


@bp.route("/<int:agency_id>/admin-panel/help/<article_id>")
def admin_help_article(agency_id: int, article_id: str) -> Any:
    article = get_help_article(article_id)
    if article is None:
        abort(404)
    return render_template("admin_help_article.html", agency_id=agency_id, article=article, admin=True)
