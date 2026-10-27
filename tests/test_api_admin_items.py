"""The JSON endpoints for admin items and tags, driven over real HTTP."""

from http import HTTPStatus
from typing import Any, Final

from flask.testing import FlaskClient
from sqlalchemy.orm import Session

from app.auth.constants import WHITE_HEX
from app.auth.models import ItemTag
from app.inventory.constants import UPC_GENERATION_PREFIX
from app.inventory.models import Item
from tests.factories import AgencyFixture, build_agency, build_item

ITEM_MIN: Final[int] = 3
ITEM_MAX: Final[int] = 12
REAL_SECONDARY_UPC: Final[str] = "012345678905"
TAG_COLOR: Final[str] = "#336699"
V1_PAGE: Final[str] = "/inventory/{agency_id}/admin-panel/items-and-tags"


def _api(agency_id: int, path: str) -> str:
    return f"/api/v1/agencies/{agency_id}/admin{path}"


def _item_body(**extra: Any) -> dict[str, Any]:
    return {"name": "Burn Dressing", "min_quantity": ITEM_MIN, "max_quantity": ITEM_MAX, "batch_size": 1} | extra


def _reloaded_item(session: Session, item_id: int) -> Item:
    item = session.get(Item, item_id)
    assert item is not None
    return item


def _build_tag(session: Session, agency_id: int, name: str = "Airway") -> ItemTag:
    tag = ItemTag(agency_id=agency_id, tag_name=name, color=TAG_COLOR, active=True)
    session.add(tag)
    session.commit()
    return tag


def test_the_item_list_carries_every_editable_field(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    response = admin_client.get(_api(agency.id, "/items"))

    assert response.status_code == HTTPStatus.OK
    [item] = response.get_json()
    assert item["id"] == agency.item.id
    assert item["name"] == agency.item.name
    assert item["secondary_upcs"] == []
    assert item["tag_ids"] == []
    assert item["min_quantity"] == agency.item.min_quantity


def test_the_item_list_stops_at_the_agency_boundary(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    build_item(session, build_agency(session).id, name="Someone Elses Splint")
    session.commit()

    names = {item["name"] for item in admin_client.get(_api(agency.id, "/items")).get_json()}

    assert names == {agency.item.name}


def test_a_locked_browser_may_not_read_the_item_list(client: FlaskClient, agency: AgencyFixture) -> None:
    response = client.get(_api(agency.id, "/items"))

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_a_locked_browser_may_not_add_a_tag(client: FlaskClient, agency: AgencyFixture) -> None:
    response = client.post(_api(agency.id, "/tags"), json={"tag_name": "Airway", "color": TAG_COLOR})

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_adding_an_item_saves_it_and_answers_with_the_saved_row(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    response = admin_client.post(_api(agency.id, "/items"), json=_item_body(secondary_upcs=[REAL_SECONDARY_UPC]))

    assert response.status_code == HTTPStatus.CREATED
    body = response.get_json()
    assert body["name"] == "Burn Dressing"
    assert body["secondary_upcs"] == [REAL_SECONDARY_UPC]
    assert session.get(Item, body["id"]) is not None


def test_an_item_whose_maximum_is_not_above_its_minimum_is_refused(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    response = admin_client.post(_api(agency.id, "/items"), json=_item_body(max_quantity=ITEM_MIN))

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_an_item_may_not_carry_a_generated_upc_as_a_secondary_barcode(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    generated = f"{UPC_GENERATION_PREFIX}{'0' * (12 - len(UPC_GENERATION_PREFIX))}"

    response = admin_client.post(_api(agency.id, "/items"), json=_item_body(secondary_upcs=[generated]))

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_an_item_may_not_be_tagged_with_another_agencys_tag(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    other_tag = _build_tag(session, build_agency(session).id, name="Theirs")

    response = admin_client.post(_api(agency.id, "/items"), json=_item_body(tag_ids=[other_tag.id]))

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_an_unknown_field_on_an_item_is_refused_rather_than_ignored(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    response = admin_client.post(_api(agency.id, "/items"), json=_item_body(sneaky_field="yes"))

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_saving_an_item_replaces_its_row(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    response = admin_client.patch(_api(agency.id, f"/items/{agency.item.id}"), json=_item_body(name="Renamed Gauze"))

    assert response.status_code == HTTPStatus.OK
    assert response.get_json()["name"] == "Renamed Gauze"
    session.expire_all()
    assert _reloaded_item(session, agency.item.id).name == "Renamed Gauze"


def test_another_agencys_item_is_not_found(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    other_item = build_item(session, build_agency(session).id, name="Theirs")
    session.commit()

    response = admin_client.patch(_api(agency.id, f"/items/{other_item.id}"), json=_item_body())

    assert response.status_code == HTTPStatus.NOT_FOUND


def test_removing_an_item_hides_it_without_deleting_its_history(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    response = admin_client.delete(_api(agency.id, f"/items/{agency.item.id}"))

    assert response.status_code == HTTPStatus.NO_CONTENT
    session.expire_all()
    assert _reloaded_item(session, agency.item.id).active is False
    assert admin_client.get(_api(agency.id, "/items")).get_json() == []


def test_the_tag_list_carries_the_chip_text_color(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    tag = _build_tag(session, agency.id)

    response = admin_client.get(_api(agency.id, "/tags"))

    assert response.status_code == HTTPStatus.OK
    assert response.get_json() == [{"id": tag.id, "tag_name": "Airway", "color": TAG_COLOR, "text_color": WHITE_HEX}]


def test_adding_a_tag_saves_it(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    response = admin_client.post(_api(agency.id, "/tags"), json={"tag_name": "Airway", "color": TAG_COLOR})

    assert response.status_code == HTTPStatus.CREATED
    assert response.get_json()["tag_name"] == "Airway"


def test_a_tag_needs_a_real_color(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    response = admin_client.post(_api(agency.id, "/tags"), json={"tag_name": "Airway", "color": "not-a-color"})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_saving_a_tag_replaces_its_name_and_color(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    tag = _build_tag(session, agency.id)

    response = admin_client.patch(_api(agency.id, f"/tags/{tag.id}"), json={"tag_name": "Breathing", "color": "#112233"})

    assert response.status_code == HTTPStatus.OK
    assert response.get_json()["tag_name"] == "Breathing"


def test_another_agencys_tag_is_not_found(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    other_tag = _build_tag(session, build_agency(session).id, name="Theirs")

    response = admin_client.patch(_api(agency.id, f"/tags/{other_tag.id}"), json={"tag_name": "Mine", "color": TAG_COLOR})

    assert response.status_code == HTTPStatus.NOT_FOUND


def test_removing_a_tag_drops_it_from_the_list(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    tag = _build_tag(session, agency.id)

    response = admin_client.delete(_api(agency.id, f"/tags/{tag.id}"))

    assert response.status_code == HTTPStatus.NO_CONTENT
    assert admin_client.get(_api(agency.id, "/tags")).get_json() == []


def test_the_v1_data_page_still_renders(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    response = admin_client.get(V1_PAGE.format(agency_id=agency.id))

    assert response.status_code == HTTPStatus.OK
