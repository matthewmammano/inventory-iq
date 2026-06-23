"""UPC review and lookup workflow."""

import re
from difflib import SequenceMatcher

from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.alerts.constants import AlertAction, AlertType
from app.alerts.models import AlertRecords
from app.auth.models import AgencyEmails
from app.shared.clock import utc_now

from .constants import (
    UNKNOWN_UPC_IGNORED_MESSAGE,
    UNKNOWN_UPC_LINKED_MESSAGE,
    UNKNOWN_UPC_REVIEW_MESSAGE,
    UPC_GENERATION_PREFIX,
    UnknownUpcStatus,
)
from .models import Items, ItemSecondaryUpc, UnknownUpcScan, agency_upc_exists, validate_upc_code
from .upc_lookup_service import lookup_upc_title

MIN_SUGGESTION_SCORE = 0.55


def record_unknown_upc(session: Session, agency_id: int, upc: str) -> UnknownUpcStatus:
    normalized = validate_upc_code(upc)
    if agency_upc_exists(session, agency_id, normalized):
        return UnknownUpcStatus.RESOLVED
    if normalized.startswith(UPC_GENERATION_PREFIX):
        raise ValueError("Private UPCs must already be linked as primary item UPCs.")
    existing = _unknown_upc(session, agency_id, normalized)
    if existing is not None:
        existing.updated_at = utc_now()
        return existing.status

    lookup_title = _clean_lookup_title(lookup_upc_title(normalized))
    closest_item = _closest_item(session, agency_id, lookup_title)
    suggested_item_id, suggested_item_name, suggestion_score = closest_item or (None, None, None)
    scan = UnknownUpcScan(
        agency_id=agency_id,
        upc=normalized,
        lookup_title=lookup_title,
        suggested_item_id=suggested_item_id,
    )
    try:
        with session.begin_nested():
            session.add(scan)
            session.flush()
    except IntegrityError:
        existing = _unknown_upc(session, agency_id, normalized)
        if existing is not None:
            existing.updated_at = utc_now()
        logger.info(
            "Duplicate unknown UPC scan merged into existing review row",
            extra={"agency_id": agency_id, "upc": normalized},
        )
        return existing.status if existing is not None else UnknownUpcStatus.PENDING
    recipient_count = _queue_unknown_upc_alerts(session, agency_id, scan)
    logger.info(
        "Unknown UPC queued for admin review",
        extra={
            "agency_id": agency_id,
            "unknown_upc_id": scan.id,
            "upc": normalized,
            "lookup_title": lookup_title,
            "closest_item_id": suggested_item_id,
            "closest_item_name": suggested_item_name,
            "closest_score": round(suggestion_score, 3) if suggestion_score is not None else None,
            "suggested_item_id": suggested_item_id,
            "recipient_count": recipient_count,
        },
    )
    return UnknownUpcStatus.PENDING


def list_review_unknown_upcs(session: Session, agency_id: int) -> list[UnknownUpcScan]:
    return list(
        session.execute(
            select(UnknownUpcScan)
            .options(joinedload(UnknownUpcScan.suggested_item))
            .where(
                UnknownUpcScan.agency_id == agency_id,
                UnknownUpcScan.status.in_([UnknownUpcStatus.PENDING, UnknownUpcStatus.IGNORE]),
            )
            .order_by(UnknownUpcScan.status, UnknownUpcScan.updated_at.desc(), UnknownUpcScan.id.desc())
        )
        .scalars()
        .all()
    )


def unknown_upc_scan_message(status: UnknownUpcStatus) -> str:
    if status == UnknownUpcStatus.IGNORE:
        return UNKNOWN_UPC_IGNORED_MESSAGE
    if status == UnknownUpcStatus.RESOLVED:
        return UNKNOWN_UPC_LINKED_MESSAGE
    return UNKNOWN_UPC_REVIEW_MESSAGE


def resolve_unknown_upc(session: Session, agency_id: int, unknown_upc_id: int, item_id: int) -> None:
    scan = _review_unknown_by_id(session, agency_id, unknown_upc_id)
    item = session.scalar(select(Items).where(Items.agency_id == agency_id, Items.id == item_id))
    if scan is None or item is None:
        raise ValueError("UPC review row or item not found.")
    if scan.upc.startswith(UPC_GENERATION_PREFIX):
        raise ValueError(f"Secondary UPCs cannot start with {UPC_GENERATION_PREFIX}.")
    if agency_upc_exists(session, agency_id, scan.upc):
        raise ValueError("UPC is already linked to an item.")

    session.add(ItemSecondaryUpc(agency_id=agency_id, item_id=item.id, upc=scan.upc))
    scan.status = UnknownUpcStatus.RESOLVED
    _clear_unknown_upc_alerts(session, agency_id, scan.upc)


def ignore_unknown_upc(session: Session, agency_id: int, unknown_upc_id: int) -> None:
    scan = _review_unknown_by_id(session, agency_id, unknown_upc_id)
    if scan is None:
        raise ValueError("UPC review row not found.")
    scan.status = UnknownUpcStatus.IGNORE
    _clear_unknown_upc_alerts(session, agency_id, scan.upc)


def unignore_unknown_upc(session: Session, agency_id: int, unknown_upc_id: int) -> None:
    scan = _ignored_unknown_by_id(session, agency_id, unknown_upc_id)
    if scan is None:
        raise ValueError("Ignored UPC not found.")
    scan.status = UnknownUpcStatus.PENDING
    scan.updated_at = utc_now()
    _queue_unknown_upc_alerts(session, agency_id, scan)


def remove_unknown_upc(session: Session, agency_id: int, unknown_upc_id: int) -> None:
    scan = _review_unknown_by_id(session, agency_id, unknown_upc_id)
    if scan is None:
        raise ValueError("UPC review row not found.")
    _clear_unknown_upc_alerts(session, agency_id, scan.upc)
    session.delete(scan)


def _unknown_upc(session: Session, agency_id: int, upc: str) -> UnknownUpcScan | None:
    return session.scalar(select(UnknownUpcScan).where(UnknownUpcScan.agency_id == agency_id, UnknownUpcScan.upc == upc))


def _review_unknown_by_id(session: Session, agency_id: int, unknown_upc_id: int) -> UnknownUpcScan | None:
    return session.scalar(
        select(UnknownUpcScan).where(
            UnknownUpcScan.agency_id == agency_id,
            UnknownUpcScan.id == unknown_upc_id,
            UnknownUpcScan.status.in_([UnknownUpcStatus.PENDING, UnknownUpcStatus.IGNORE]),
        )
    )


def _ignored_unknown_by_id(session: Session, agency_id: int, unknown_upc_id: int) -> UnknownUpcScan | None:
    return session.scalar(
        select(UnknownUpcScan).where(
            UnknownUpcScan.agency_id == agency_id,
            UnknownUpcScan.id == unknown_upc_id,
            UnknownUpcScan.status == UnknownUpcStatus.IGNORE,
        )
    )


def _queue_unknown_upc_alerts(session: Session, agency_id: int, scan: UnknownUpcScan) -> int:
    rows = session.execute(select(AgencyEmails).where(AgencyEmails.agency_id == agency_id).order_by(AgencyEmails.id)).scalars()
    count = 0
    for recipient in rows:
        session.add(
            AlertRecords(
                agency_id=agency_id,
                agency_email_id=recipient.id,
                type=AlertType.UNKNOWN_UPC,
                details_json={
                    "upc": scan.upc,
                    "lookup_title": scan.lookup_title,
                    "unknown_upc_id": scan.id,
                    "created_at": scan.created_at.isoformat(),
                },
            )
        )
        count += 1
    return count


def _closest_item(session: Session, agency_id: int, lookup_title: str | None) -> tuple[int, str, float] | None:
    if not lookup_title:
        return None
    rows = session.execute(
        select(Items.id, Items.name).where(
            Items.agency_id == agency_id,
            Items.active.is_(True),
        )
    ).all()
    scored = [(_match_score(lookup_title, item_name), item_id, item_name) for item_id, item_name in rows]
    score, item_id, item_name = max(scored, default=(0.0, None, ""))
    if item_id is None or score < MIN_SUGGESTION_SCORE:
        return None
    return item_id, item_name, score


def _clean_lookup_title(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.replace("®", "").replace("™", "")
    cleaned = re.sub(r"\\x[0-9a-fA-F]{2}", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")
    if cleaned and cleaned == cleaned.lower():
        cleaned = cleaned.title()
    return cleaned or None


def _match_score(left: str, right: str) -> float:
    left_text = _normalize_match_text(left)
    right_text = _normalize_match_text(right)
    if not left_text or not right_text:
        return 0.0

    left_tokens = set(left_text.split())
    right_tokens = set(right_text.split())
    return max(
        SequenceMatcher(None, left_text, right_text).ratio(),
        _token_overlap_score(left_tokens, right_tokens),
        _token_subset_score(left_tokens, right_tokens),
        _substring_score(left_text, right_text),
    )


def _normalize_match_text(value: str) -> str:
    words = re.sub(r"[^a-z0-9]+", " ", value.lower()).split()
    return " ".join(_normalize_match_word(word) for word in words)


def _normalize_match_word(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return f"{word[:-3]}y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _token_overlap_score(left_tokens: set[str], right_tokens: set[str]) -> float:
    if not left_tokens or not right_tokens:
        return 0.0
    shared = left_tokens & right_tokens
    precision = len(shared) / len(right_tokens)
    recall = len(shared) / len(left_tokens)
    if precision == 0 or recall == 0:
        return 0.0
    return (2 * precision * recall) / (precision + recall)


def _token_subset_score(left_tokens: set[str], right_tokens: set[str]) -> float:
    shorter_tokens, longer_tokens = sorted((left_tokens, right_tokens), key=len)
    if len(shorter_tokens) < 2 or not shorter_tokens.issubset(longer_tokens):
        return 0.0
    return 0.9 + min(len(shorter_tokens), 5) * 0.02


def _substring_score(left: str, right: str) -> float:
    shorter, longer = sorted((left, right), key=len)
    if shorter not in longer or len(shorter.split()) < 2:
        return 0.0
    length_ratio = len(shorter) / max(len(longer), 1)
    return 0.88 + min(length_ratio, 1.0) * 0.12


def _clear_unknown_upc_alerts(session: Session, agency_id: int, upc: str) -> None:
    alerts = session.execute(
        select(AlertRecords).where(
            AlertRecords.agency_id == agency_id,
            AlertRecords.type == AlertType.UNKNOWN_UPC,
            AlertRecords.action == AlertAction.PENDING,
        )
    ).scalars()
    for alert in alerts:
        if alert.details_json.get("upc") == upc:
            alert.action = AlertAction.CLEARED
            alert.action_at = utc_now()
