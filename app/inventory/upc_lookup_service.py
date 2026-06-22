"""External UPC title lookup adapter."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from loguru import logger

UPCITEMDB_TRIAL_LOOKUP_URL = "https://api.upcitemdb.com/prod/trial/lookup"
LOOKUP_TIMEOUT_SECONDS = 3
MAX_LOOKUP_TITLE_LENGTH = 255


def lookup_upc_title(upc: str) -> str | None:
    """Return a product title suggestion from UPCitemdb free lookup."""
    url = f"{UPCITEMDB_TRIAL_LOOKUP_URL}?upc={quote(upc)}"
    request = Request(url, headers={"User-Agent": "InventoryIQ/1.0"})
    try:
        with urlopen(request, timeout=LOOKUP_TIMEOUT_SECONDS) as response:  # nosec B310 - fixed HTTPS UPC lookup URL.
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.warning("UPC title lookup failed", extra={"upc": upc, "error": str(exc)})
        return None

    if payload.get("code") != "OK":
        return None
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return None
    first = items[0]
    if not isinstance(first, dict):
        return None
    title = str(first.get("title") or "").strip()
    return title[:MAX_LOOKUP_TITLE_LENGTH] or None
