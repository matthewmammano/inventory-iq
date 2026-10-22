"""Admin navigation: the dashboard's Go To grid and the hub pages that group its destinations."""

from dataclasses import dataclass

from flask import request, url_for


@dataclass(frozen=True, slots=True)
class NavLink:
    """One destination before a URL exists for it."""

    title: str
    detail: str
    endpoint: str
    primary: bool = False


@dataclass(frozen=True, slots=True)
class NavCard:
    """One tappable destination as a template renders it."""

    title: str
    detail: str
    url: str
    primary: bool


@dataclass(frozen=True, slots=True)
class NavHub:
    """A dashboard button that opens a short menu instead of a screen."""

    title: str
    detail: str
    subtitle: str
    instructions: str
    links: tuple[NavLink, ...]


NAV_HUBS: dict[str, NavHub] = {
    "update-stock": NavHub(
        title="Update Stock",
        detail="Scan items, or type counts for a whole location.",
        subtitle="Change what is on the shelf",
        instructions="Scanning is fastest for a few items. The typing grid is faster when you are going through a whole location at once.",
        links=(
            NavLink("Scan Items", "Scan a barcode to count, restock, take out, or transfer.", "admin.admin_scan_items", primary=True),
            NavLink("Bulk Edit", "Type counts for a whole location without scanning anything.", "admin.bulk_edit", primary=True),
        ),
    ),
    "items-and-labels": NavHub(
        title="Items & Labels",
        detail="Set up items, tags, barcodes, and shelf cards.",
        subtitle="Set up what you stock",
        instructions="This is where items get created and named. Do this first; everything else on the dashboard reads from it.",
        links=(
            NavLink("Items & Tags", "Add or edit items, tags, and who gets emails.", "admin.items_and_tags"),
            NavLink("Unknown Barcodes", "Link or ignore barcodes nobody set up yet.", "admin.unknown_barcodes"),
            NavLink("Print Labels", "Print shelf cards with names and barcodes.", "admin.print_labels"),
        ),
    ),
}

DASHBOARD_LINKS: tuple[NavLink, ...] = (
    NavLink(NAV_HUBS["update-stock"].title, NAV_HUBS["update-stock"].detail, "hub:update-stock", primary=True),
    NavLink("Restock Report", "See what to reorder and how much.", "admin.restock", primary=True),
    NavLink("Stock Levels", "Review counts across every location.", "admin.stock_levels"),
    NavLink("History", "See all past inventory changes.", "admin.admin_history"),
    NavLink(NAV_HUBS["items-and-labels"].title, NAV_HUBS["items-and-labels"].detail, "hub:items-and-labels"),
)

_HUB_PREFIX = "hub:"


def nav_cards(links: tuple[NavLink, ...], agency_id: int) -> list[NavCard]:
    """Resolve each link to a URL, sending `hub:<slug>` endpoints to the hub page for that slug."""
    return [NavCard(link.title, link.detail, _link_url(link, agency_id), link.primary) for link in links]


def _link_url(link: NavLink, agency_id: int) -> str:
    if link.endpoint.startswith(_HUB_PREFIX):
        return url_for("admin.admin_hub", agency_id=agency_id, hub_slug=link.endpoint.removeprefix(_HUB_PREFIX))
    return url_for(link.endpoint, agency_id=agency_id)


HUB_SLUG_BY_ENDPOINT: dict[str, str] = {link.endpoint: slug for slug, hub in NAV_HUBS.items() for link in hub.links}


def hub_back_url() -> str | None:
    """The hub that owns the current page, so its Back button returns to the menu it was opened from."""
    slug = HUB_SLUG_BY_ENDPOINT.get(request.endpoint or "")
    agency_id = (request.view_args or {}).get("agency_id")
    if slug is None or agency_id is None:
        return None
    return url_for("admin.admin_hub", agency_id=agency_id, hub_slug=slug)
