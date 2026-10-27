"""Every v1 admin and guest page still renders while its logic moves to the JSON API."""

from http import HTTPStatus

import pytest
from flask import Flask
from flask.testing import FlaskClient

from tests.factories import AgencyFixture

AGENCY_ARGUMENT = "agency_id"
V1_BLUEPRINTS = ("admin.", "guest.")


def _agency_page_endpoints(app: Flask) -> list[str]:
    """Every v1 GET page a signed-in agency can open with nothing but its own id."""
    return sorted(
        rule.endpoint
        for rule in app.url_map.iter_rules()
        if rule.endpoint.startswith(V1_BLUEPRINTS) and "GET" in (rule.methods or set()) and rule.arguments == {AGENCY_ARGUMENT}
    )


def test_the_v1_page_list_is_not_silently_empty(app: Flask) -> None:
    assert len(_agency_page_endpoints(app)) > 5


def test_every_v1_agency_page_still_renders(app: Flask, admin_client: FlaskClient, agency: AgencyFixture) -> None:
    broken = {}
    for endpoint in _agency_page_endpoints(app):
        with app.test_request_context():
            url = app.url_map.bind("localhost").build(endpoint, {AGENCY_ARGUMENT: agency.id})
        status = admin_client.get(url, follow_redirects=True).status_code
        if status != HTTPStatus.OK:
            broken[endpoint] = status

    assert broken == {}


@pytest.mark.parametrize("endpoint", ["admin.admin_panel", "guest.index"])
def test_a_browser_that_never_unlocked_admin_is_sent_away_from_an_admin_page(
    app: Flask,
    client: FlaskClient,
    agency: AgencyFixture,
    endpoint: str,
) -> None:
    with app.test_request_context():
        url = app.url_map.bind("localhost").build(endpoint, {AGENCY_ARGUMENT: agency.id})

    response = client.get(url)

    assert response.status_code == (HTTPStatus.FOUND if endpoint.startswith("admin.") else HTTPStatus.OK)
