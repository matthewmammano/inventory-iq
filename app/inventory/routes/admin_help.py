"""Admin help center routes."""

from typing import Any

from flask import abort, render_template

from app.admin_help.articles import get_help_article, list_help_articles, list_help_tags
from app.inventory import admin_bp as bp


@bp.route("/<squad>/admin-panel/help")
def admin_help(squad: str) -> Any:
    articles = list_help_articles()
    return render_template(
        "admin_help.html",
        squad=squad,
        articles=articles,
        tags=list_help_tags(articles),
        admin=True,
    )


@bp.route("/<squad>/admin-panel/help/<article_id>")
def admin_help_article(squad: str, article_id: str) -> Any:
    article = get_help_article(article_id)
    if article is None:
        abort(404)
    return render_template("admin_help_article.html", squad=squad, article=article, admin=True)
