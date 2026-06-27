"""UPC review and lookup workflow."""

import re
from collections.abc import Iterable
from difflib import SequenceMatcher
from typing import cast

from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.alerts.alert_service import cancel_unknown_upc_event, queue_unknown_upc_event
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

MIN_SUGGESTION_SCORE = 0.3
MATCH_EQUIVALENCES = (
    ("bvm", "bag valve mask", "resuscitator", "resuscitator"),
    ("child", "pediatric", "paediatric"),
    ("infant", "neonatal", "newborn"),
    ("nrb", "non rebreather", "nonrebreather"),
    ("nc", "nasal cannula"),
    ("bp", "blood pressure", "sphygmomanometer"),
    ("ccollar", "cervical collar", "c collar"),
    ("oral", "oropharyngeal", "opa", "guedel", "berman"),
    ("nasal", "nasopharyngeal", "npa"),
    ("yankauer set", "suction tip", "suction handle"),
    ("oximeter", "ox"),
    ("shear", "shears", "scissors"),
    ("quick", "hemostatic"),
    ("cravat", "triangular"),
    ("ice", "cold"),
    ("faceshield", "face shield"),
    ("small volume", "nebulizer"),
    ("mega mover", "portable transport unit"),
    ("lifeband", "life band"),
    ("aed pad", "padz", "pads", "electrodes"),
    ("quick clot", "quikclot", "hemostatic", "combat gauze"),
)
SINGLE_TOKEN_MIN_SCORE = 0.38


def record_unknown_upc(session: Session, agency_id: int, upc: str) -> UnknownUpcStatus:
    normalized = validate_upc_code(upc)
    if _active_upc_exists(session, agency_id, normalized):
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
    _queue_unknown_upc_alert(session, agency_id, scan)
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
    item = session.scalar(select(Items).where(Items.agency_id == agency_id, Items.id == item_id, Items.active.is_(True)))
    if scan is None or item is None:
        raise ValueError("UPC review row or item not found.")
    if scan.upc.startswith(UPC_GENERATION_PREFIX):
        raise ValueError(f"Secondary UPCs cannot start with {UPC_GENERATION_PREFIX}.")
    if agency_upc_exists(session, agency_id, scan.upc):
        raise ValueError("UPC is already linked to an item.")

    existing = session.scalar(select(ItemSecondaryUpc).where(ItemSecondaryUpc.agency_id == agency_id, ItemSecondaryUpc.upc == scan.upc))
    if existing:
        existing.item_id = item.id
        existing.active = True
    else:
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


def _active_upc_exists(session: Session, agency_id: int, upc: str) -> bool:
    return (
        session.scalar(select(Items.id).where(Items.agency_id == agency_id, Items.upc == upc, Items.active.is_(True))) is not None
        or session.scalar(
            select(ItemSecondaryUpc.id).where(
                ItemSecondaryUpc.agency_id == agency_id,
                ItemSecondaryUpc.upc == upc,
                ItemSecondaryUpc.active.is_(True),
            )
        )
        is not None
    )


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
    _queue_unknown_upc_alert(session, agency_id, scan)
    return 1


def _queue_unknown_upc_alert(session: Session, agency_id: int, scan: UnknownUpcScan) -> None:
    queue_unknown_upc_event(
        session,
        agency_id,
        unknown_upc_id=scan.id,
        upc=scan.upc,
        lookup_title=scan.lookup_title,
        created_at=scan.created_at,
    )


def _closest_item(session: Session, agency_id: int, lookup_title: str | None) -> tuple[int, str, float] | None:
    rows = cast(
        "list[tuple[int, str]]",
        session.execute(
            select(Items.id, Items.name).where(
                Items.agency_id == agency_id,
                Items.active.is_(True),
            )
        )
        .tuples()
        .all(),
    )
    return suggest_item_match(lookup_title, rows)


def suggest_item_match(lookup_title: str | None, items: Iterable[tuple[int, str]]) -> tuple[int, str, float] | None:
    if not lookup_title:
        return None
    scored = [(_match_score(lookup_title, item_name), item_id, item_name) for item_id, item_name in items]
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
    shared_tokens = left_tokens & right_tokens
    if not shared_tokens:
        return 0.0
    if len(shared_tokens) == 1 and len(right_tokens) > 1 and not _single_token_item_match(shared_tokens, left_tokens, right_tokens):
        return 0.0
    score = max(
        SequenceMatcher(None, left_text, right_text).ratio(),
        _token_overlap_score(left_tokens, right_tokens),
        _token_subset_score(left_tokens, right_tokens),
        _substring_score(left_text, right_text),
    )
    return min(1.0, score + _number_match_bonus(left_tokens, right_tokens))


def _normalize_match_text(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", value.lower())
    text = re.sub(r"\b(\d+)\s+(ml|mm|fr|mg)\b", r"\1\2", text)
    text = re.sub(r"\b(\d+)\s*x\s*(\d+)\b", r"\1x\2", text)
    for equivalents in MATCH_EQUIVALENCES:
        canonical = equivalents[0]
        for phrase in equivalents:
            text = re.sub(_phrase_pattern(phrase), canonical, text)
    words = text.split()
    words = _apply_unordered_equivalences(words)
    return " ".join(_normalize_match_word(word) for word in words)


def _phrase_pattern(phrase: str) -> str:
    words = [re.escape(word) for word in phrase.split()]
    return rf"\b{'[^a-z0-9]+'.join(words)}\b"


def _normalize_match_word(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return f"{word[:-3]}y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _apply_unordered_equivalences(words: list[str]) -> list[str]:
    token_set = set(words)
    for equivalents in MATCH_EQUIVALENCES:
        canonical_tokens = equivalents[0].split()
        for phrase in equivalents:
            phrase_tokens = phrase.split()
            if len(phrase_tokens) > 1 and set(phrase_tokens).issubset(token_set):
                words = [word for word in words if word not in phrase_tokens] + canonical_tokens
                token_set = set(words)
                break
    return words


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
    if len(right_tokens) == 1 and right_tokens.issubset(left_tokens):
        return 0.84
    if len(shorter_tokens) < 2 or not shorter_tokens.issubset(longer_tokens):
        return 0.0
    return 0.9 + min(len(shorter_tokens), 5) * 0.02


def _substring_score(left: str, right: str) -> float:
    shorter, longer = sorted((left, right), key=len)
    if shorter not in longer:
        return 0.0
    if len(shorter.split()) < 2:
        return SINGLE_TOKEN_MIN_SCORE
    length_ratio = len(shorter) / max(len(longer), 1)
    return 0.88 + min(length_ratio, 1.0) * 0.12


def _number_match_bonus(left_tokens: set[str], right_tokens: set[str]) -> float:
    left_numbers = {number for token in left_tokens for number in re.findall(r"\d+", token)}
    right_numbers = {number for token in right_tokens for number in re.findall(r"\d+", token)}
    return 0.12 if left_numbers & right_numbers else 0.0


def _single_token_item_match(shared_tokens: set[str], left_tokens: set[str], right_tokens: set[str]) -> bool:
    token = next(iter(shared_tokens))
    return len(right_tokens) == 1 and token in left_tokens


def _clear_unknown_upc_alerts(session: Session, agency_id: int, upc: str) -> None:
    cancel_unknown_upc_event(session, agency_id, upc)
