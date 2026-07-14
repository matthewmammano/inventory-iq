"""Cryptographically secure short-lived numeric codes (PINs)."""

import secrets


def generate_numeric_pin(digits: int) -> str:
    """Return a random zero-padded numeric string of the given length, e.g. '0417'."""
    return f"{secrets.randbelow(10**digits):0{digits}d}"
