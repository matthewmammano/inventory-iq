"""Page windows and the footer link row that renders them."""

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

PAGE_LINK_GAP = "..."
NEIGHBOR_PAGES = 1


@dataclass(frozen=True, slots=True)
class PageLink:
    """One footer entry; an empty url marks the gap between distant page numbers."""

    label: str
    url: str = ""
    current: bool = False


@dataclass(frozen=True, slots=True)
class PageNav:
    """Everything a paginated view needs to draw its footer controls."""

    page: int
    total_pages: int
    links: tuple[PageLink, ...]
    previous_url: str
    next_url: str
    jump_action: str
    jump_fields: tuple[tuple[str, str], ...]

    @property
    def is_needed(self) -> bool:
        return self.total_pages > 1


@dataclass(frozen=True, slots=True)
class PageWindow:
    """A requested page against a known row count."""

    page: int
    total_rows: int
    page_size: int

    @property
    def total_pages(self) -> int:
        return max(-(-self.total_rows // self.page_size), 1)

    @property
    def current_page(self) -> int:
        return min(max(self.page, 1), self.total_pages)


def build_page_nav(
    window: PageWindow,
    *,
    url_for_page: Callable[[int], str],
    jump_action: str,
    jump_fields: Iterable[tuple[str, str]] = (),
) -> PageNav:
    """Build the footer link row for one page window."""
    page = window.current_page
    total_pages = window.total_pages
    return PageNav(
        page=page,
        total_pages=total_pages,
        links=tuple(_page_links(page, total_pages, url_for_page)),
        previous_url=url_for_page(page - 1) if page > 1 else "",
        next_url=url_for_page(page + 1) if page < total_pages else "",
        jump_action=jump_action,
        jump_fields=tuple(jump_fields),
    )


def _page_links(page: int, total_pages: int, url_for_page: Callable[[int], str]) -> Iterator[PageLink]:
    previous = 0
    for number in _shown_pages(page, total_pages):
        if number - previous > 1:
            yield PageLink(PAGE_LINK_GAP)
        yield PageLink(str(number), url_for_page(number), number == page)
        previous = number


def _shown_pages(page: int, total_pages: int) -> list[int]:
    edges = {1, total_pages}
    neighbors = {number for number in range(page - NEIGHBOR_PAGES, page + NEIGHBOR_PAGES + 1) if 1 <= number <= total_pages}
    return sorted(edges | neighbors)
