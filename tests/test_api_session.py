"""The endpoint that tells the frontend which agency it is signed in as."""

from http import HTTPStatus

from flask.testing import FlaskClient

from tests.factories import AgencyFixture

ME_ROUTE = "/api/v1/me"


def test_the_session_endpoint_names_the_signed_in_agency(client: FlaskClient, agency: AgencyFixture) -> None:
    response = client.get(ME_ROUTE)

    assert response.status_code == HTTPStatus.OK
    body = response.get_json()
    assert body["id"] == agency.id
    assert body["display_name"] == agency.agency.display_name
    assert body["logo_url"].startswith("/static/")


def test_the_session_endpoint_refuses_an_anonymous_browser(anonymous_client: FlaskClient) -> None:
    assert anonymous_client.get(ME_ROUTE).status_code == HTTPStatus.UNAUTHORIZED
