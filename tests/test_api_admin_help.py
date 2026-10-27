"""The JSON endpoints behind the admin help center, driven over real HTTP."""

from http import HTTPStatus
from typing import Final

from flask.testing import FlaskClient
from sqlalchemy.orm import Session

from app.admin_help.articles import list_help_articles
from tests.factories import AgencyFixture, build_agency

KNOWN_ARTICLE_ID: Final[str] = "handling-unknown-barcodes"
UNKNOWN_ARTICLE_ID: Final[str] = "no-such-article"
V1_HELP_PAGE: Final[str] = "/inventory/{agency_id}/admin-panel/help"
V1_ARTICLE_PAGE: Final[str] = "/inventory/{agency_id}/admin-panel/help/{article_id}"


def _api(agency_id: int, path: str = "") -> str:
    return f"/api/v1/agencies/{agency_id}/admin/help/articles{path}"


def test_the_index_lists_every_article_with_its_tags(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    response = admin_client.get(_api(agency.id))

    assert response.status_code == HTTPStatus.OK
    body = response.get_json()
    assert len(body["articles"]) == len(list_help_articles())
    article = next(entry for entry in body["articles"] if entry["id"] == KNOWN_ARTICLE_ID)
    assert article["title"]
    assert article["summary"]
    assert article["tags"]
    assert "body_html" not in article


def test_the_index_tags_are_the_deduplicated_tags_of_its_articles(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    body = admin_client.get(_api(agency.id)).get_json()

    tag_keys = [tag.casefold() for tag in body["tags"]]
    assert len(tag_keys) == len(set(tag_keys))
    assert set(tag_keys) == {tag.casefold() for entry in body["articles"] for tag in entry["tags"]}


def test_an_index_entry_carries_the_text_its_search_box_matches_on(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    body = admin_client.get(_api(agency.id)).get_json()

    article = next(entry for entry in body["articles"] if entry["id"] == KNOWN_ARTICLE_ID)
    assert article["title"].casefold().split()[0] in article["search_text"]


def test_one_article_comes_back_as_rendered_html(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    response = admin_client.get(_api(agency.id, f"/{KNOWN_ARTICLE_ID}"))

    assert response.status_code == HTTPStatus.OK
    body = response.get_json()
    assert body["id"] == KNOWN_ARTICLE_ID
    assert body["title"]
    assert body["tags"]
    assert "<p>" in body["body_html"]
    assert "body_markdown" not in body


def test_an_article_body_carries_no_unrendered_markdown(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    body_html = admin_client.get(_api(agency.id, f"/{KNOWN_ARTICLE_ID}")).get_json()["body_html"]

    assert "**" not in body_html
    assert not body_html.lstrip().startswith("#")


def test_an_unknown_article_id_is_not_found(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    response = admin_client.get(_api(agency.id, f"/{UNKNOWN_ARTICLE_ID}"))

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert "help article" in response.get_json()["message"]


def test_the_help_endpoints_refuse_a_browser_that_has_not_unlocked_admin(client: FlaskClient, agency: AgencyFixture) -> None:
    assert client.get(_api(agency.id)).status_code == HTTPStatus.FORBIDDEN
    assert client.get(_api(agency.id, f"/{KNOWN_ARTICLE_ID}")).status_code == HTTPStatus.FORBIDDEN


def test_another_agencys_help_path_is_refused(admin_client: FlaskClient, session: Session) -> None:
    other = build_agency(session)

    assert admin_client.get(_api(other.id)).status_code == HTTPStatus.FORBIDDEN


def test_the_v1_help_pages_still_answer(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    index_response = admin_client.get(V1_HELP_PAGE.format(agency_id=agency.id))
    article_response = admin_client.get(V1_ARTICLE_PAGE.format(agency_id=agency.id, article_id=KNOWN_ARTICLE_ID))

    assert index_response.status_code == HTTPStatus.OK
    assert article_response.status_code == HTTPStatus.OK
