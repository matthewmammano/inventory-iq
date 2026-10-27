"""The page window arithmetic and footer link row every paginated admin view uses."""

from typing import Final

import pytest

from app.shared.pagination import PAGE_LINK_GAP, PageWindow, build_page_nav

PAGE_SIZE: Final[int] = 10
JUMP_ACTION: Final[str] = "/inventory/history"


def _url(page: int) -> str:
    return f"{JUMP_ACTION}?page={page}"


def _nav(page: int, total_rows: int):
    return build_page_nav(PageWindow(page=page, total_rows=total_rows, page_size=PAGE_SIZE), url_for_page=_url, jump_action=JUMP_ACTION)


def _labels(page: int, total_rows: int) -> list[str]:
    return [link.label for link in _nav(page, total_rows).links]


@pytest.mark.parametrize(("total_rows", "expected"), [(0, 1), (1, 1), (10, 1), (11, 2), (100, 10), (101, 11)])
def test_a_partial_last_page_still_counts_as_a_page(total_rows: int, expected: int) -> None:
    assert PageWindow(page=1, total_rows=total_rows, page_size=PAGE_SIZE).total_pages == expected


@pytest.mark.parametrize(("requested", "expected"), [(0, 1), (-5, 1), (1, 1), (3, 3), (4, 3), (99, 3)])
def test_a_page_number_out_of_range_is_clamped_into_it(requested: int, expected: int) -> None:
    assert PageWindow(page=requested, total_rows=25, page_size=PAGE_SIZE).current_page == expected


def test_a_single_page_needs_no_footer() -> None:
    assert _nav(1, 10).is_needed is False
    assert _nav(1, 11).is_needed is True


def test_the_only_page_still_renders_itself_once() -> None:
    assert _labels(1, 4) == ["1"]


def test_a_short_run_of_pages_is_listed_without_a_gap() -> None:
    assert _labels(2, 30) == ["1", "2", "3"]


def test_a_middle_page_is_flanked_by_gaps_and_both_edges() -> None:
    assert _labels(5, 100) == ["1", PAGE_LINK_GAP, "4", "5", "6", PAGE_LINK_GAP, "10"]


def test_no_gap_is_drawn_where_the_pages_are_already_adjacent() -> None:
    assert _labels(2, 100) == ["1", "2", "3", PAGE_LINK_GAP, "10"]
    assert _labels(9, 100) == ["1", PAGE_LINK_GAP, "8", "9", "10"]


def test_exactly_one_link_is_marked_current_and_carries_no_url() -> None:
    nav = _nav(5, 100)
    current = [link for link in nav.links if link.current]

    assert [link.label for link in current] == ["5"]
    assert all(link.url == "" for link in nav.links if link.label == PAGE_LINK_GAP)
    assert all(link.url == _url(int(link.label)) for link in nav.links if link.label != PAGE_LINK_GAP)


def test_the_first_page_offers_no_previous_and_the_last_no_next() -> None:
    first = _nav(1, 100)
    last = _nav(10, 100)

    assert (first.previous_url, first.next_url) == ("", _url(2))
    assert (last.previous_url, last.next_url) == (_url(9), "")


def test_a_clamped_page_number_moves_the_arrows_too() -> None:
    nav = _nav(99, 100)

    assert nav.page == 10
    assert nav.next_url == ""
    assert nav.previous_url == _url(9)


def test_the_jump_form_carries_the_filters_the_view_handed_over() -> None:
    nav = build_page_nav(
        PageWindow(page=1, total_rows=100, page_size=PAGE_SIZE),
        url_for_page=_url,
        jump_action=JUMP_ACTION,
        jump_fields=(("item_id", "7"), ("sort", "newest")),
    )

    assert nav.jump_action == JUMP_ACTION
    assert nav.jump_fields == (("item_id", "7"), ("sort", "newest"))
