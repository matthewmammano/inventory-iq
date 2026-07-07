"""Best-effort IP geolocation for client diagnostics, cached per process."""

import ipaddress
import json
from dataclasses import dataclass
from urllib.request import urlopen

from loguru import logger

from app.shared.cache import ttl_cache

GEO_LOOKUP_TIMEOUT_SECONDS = 2
GEO_LOOKUP_URL = "http://ip-api.com/json/{ip}?fields=status,country,city"
GEO_CACHE_TTL_SECONDS = 900


@dataclass(frozen=True)
class GeoLocation:
    country: str | None = None
    city: str | None = None


@ttl_cache(seconds=GEO_CACHE_TTL_SECONDS, maxsize=512)
def lookup_geo(ip: str) -> GeoLocation:
    """Return country/city for a public IP, or an empty result on failure."""
    if not _is_public_ip(ip):
        return GeoLocation()
    try:
        with urlopen(GEO_LOOKUP_URL.format(ip=ip), timeout=GEO_LOOKUP_TIMEOUT_SECONDS) as response:  # nosec B310 - fixed http scheme, no user-controlled URL
            payload = json.loads(response.read())
    except (OSError, ValueError) as exc:
        logger.debug("Geo lookup failed", extra={"error": type(exc).__name__})
        return GeoLocation()

    if payload.get("status") != "success":
        return GeoLocation()
    return GeoLocation(country=payload.get("country"), city=payload.get("city"))


def _is_public_ip(ip: str) -> bool:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (address.is_private or address.is_loopback or address.is_reserved or address.is_link_local)
