"""Email address formatting helpers safe for logs."""


def email_domain(email_address: str) -> str:
    """Return only the domain portion of an email address for non-PII logs."""
    return email_address.rpartition("@")[2] or "unknown"
