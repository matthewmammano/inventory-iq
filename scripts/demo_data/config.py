"""All tunable constants for the synthetic data generator, in one place.

Change a run's behavior by editing these (or overriding via CLI flags in
generate.py); nothing else in the generator should hardcode a number.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

REFERENCE_DIR = Path(__file__).resolve().parent / "reference"

# ---------------------------------------------------------------- generation window
YEARS_BACK = 4

# ---------------------------------------------------------------- guest scan accuracy
# Of every real TAKEOUT the item's own rate says should happen:
GUEST_FORGOT_RATE = 0.07  # silently omitted: "forgot to scan" (drives balance drift)
GUEST_UNDER_RATE = 0.02  # logged at 30-80% of the true quantity
GUEST_OVER_RATE = 0.01  # logged at 130-200% of the true quantity
# remaining ~90% logs the true quantity

# ---------------------------------------------------------------- actor rule
# TAKEOUT and TRANSFER are guest self-service by default, but an admin
# occasionally logs one directly too (grabbing supplies, moving stock during a
# walkthrough), rare, sampled per event. COUNT/RESTOCK are always admin (see
# replay.py/mutation_service.py; no separate constant needed for that).
ADMIN_TAKEOUT_TRANSFER_RATE = 0.05  # share of TAKEOUT/TRANSFER volume attributed to admin instead of guest

# ---------------------------------------------------------------- global check-in cadence
# RESTOCK requires the ITEM BEING RESTOCKED (not the whole catalog) to have a
# fresh COUNT in every storage first (app/inventory/balance_service.py:
# get_required_count_storage_ids is scoped to that one item's id), so each
# item gets its own schedule. The cadence itself is ONE shared distribution
# applied independently per item (not derived from that item's own usage rate);
# deliberately simple, per-item timing variance comes from whether a check
# happens to catch it low, not from a bespoke interval per item.
COUNT_INTERVAL_MEAN_DAYS = 75
COUNT_INTERVAL_SIGMA = 0.6
COUNT_INTERVAL_CLIP_DAYS = (20, 250)
AUDIT_COUNT_NOISE_SIGMA = 0.05  # measurement noise on an otherwise-true physical recount
# Being below the reorder trigger doesn't guarantee a restock; real admins
# don't always act on it that same check-in.
RESTOCK_ACTION_PROBABILITY = 0.75
# A recount-then-restock in one visit takes real time between the two actions --
# without this, both get the exact same replayed timestamp, which is ambiguous
# to reconstruct order from later (which happened first?).
BULK_SESSION_RESTOCK_STAGGER_SECONDS = 90

# ---------------------------------------------------------------- transfers
TRANSFER_SHARE_OF_TAKEOUT = 0.25  # transfer rate as a fraction of that item's takeout rate

# ---------------------------------------------------------------- expiration tracking
# Real EMS/first-aid practice: only medications + a handful of critical/sterile
# devices get expiration-tracked. Bulk dressings, hardware, and durable equipment
# don't (hand-classified against real practice; nothing in the source data to
# learn this from).
EXPIRATION_TRACKED_ITEM_NAMES = frozenset(
    {
        "Aspirin",
        "Epi Pen - Adult",
        "Epi Pen - Child",
        "Glucose",
        "Narcan",
        "AED Battery",
        "AED Pad - Adult",
        "AED Pad - Child",
        "Glucometer Test Strips",
        "Sterile Water (250mL)",
        "Quick Clot",
        "Chest Seal",
        "Albuterol",
        "OB Kit",
        "Heat Pack",
        "Ice Pack",
    }
)
# Admin restocks a smart shelf-life estimate from the order date (not a random
# horizon draw): ~18 months covers most tracked meds/devices here. A little
# jitter spreads restocks across different points in the expiring-soon window
# relative to "today" instead of clustering at one exact offset.
RESTOCK_SHELF_LIFE_DAYS = 545
RESTOCK_SHELF_LIFE_JITTER = 0.15

# A well-run squad checks its dated stock and acts on it: pulls anything
# actually expired off the shelf (discarded, not just left sitting there
# inflating the count) and gets ahead of anything expiring soon by reordering
# it, independent of whether the item is otherwise "low." Each is its own
# per-checkpoint chance, not a certainty; a demo with 100% perfect discipline
# here wouldn't look real either.
EXPIRATION_SOON_DAYS = 30  # matches Agency.expiration_notice_days' default
EXPIRATION_DISCARD_PROBABILITY = 0.85
EXPIRATION_PROACTIVE_RESTOCK_PROBABILITY = 0.85

# ---------------------------------------------------------------- unknown UPC scans
# Real, check-digit-valid UPCs for common EMS products, each mapped onto the real
# squad item it would resolve to (user wants exactly 5, hardcoded, not random).
UNKNOWN_UPC_SEED = [
    {"upc": "076308401153", "resolve_to_item_name": "N95 Mask"},
    {"upc": "381370044444", "resolve_to_item_name": "Band-Aids"},
    {"upc": "739656008107", "resolve_to_item_name": "Tourniquet"},
    {"upc": "353885009720", "resolve_to_item_name": "Glucometer Test Strips"},
    {"upc": "312843103498", "resolve_to_item_name": "Aspirin"},
]
UNKNOWN_UPC_RESOLVE_RATE = 0.6  # fraction of the 5 that get admin-resolved during the window

# ---------------------------------------------------------------- error/correction injection
# Calibrated to real observed rates (FINDINGS.md #8), applied on top of the base
# generated event stream, independent of the guest-accuracy rates above (those
# are for guest TAKEOUT/TRANSFER; these apply to any event).
RAPID_DOUBLE_SCAN_RATE = 0.018
WRONG_OP_THEN_FIXED_RATE = 0.002

# ---------------------------------------------------------------- structural defaults
DEFAULT_AGENCY_NAME = "Squad 35 Demo"
# Placeholder logo shown for every generated demo squad (Agency.image / header logo).
DEFAULT_AGENCY_IMAGE = "https://static.wixstatic.com/media/f2696c_f18387cc47a54d47a26a772941129f95~mv2.gif"
# The app's email validator does a real MX/deliverability check, so *.example
# placeholder domains get rejected. gmail.com resolves; +tag keeps addresses
# distinct without needing a fake domain.
DEFAULT_AGENCY_EMAIL = "mattmammano+squad35demo@gmail.com"
# "1234" fails the app's real password_requirements_error check (10+ chars, a
# letter, a digit, a symbol), explicitly requested anyway; setup.py sets it via
# a direct hash instead of Agency.set_password() to bypass that one check.
DEFAULT_AGENCY_PASSWORD = "1234"
DEFAULT_AGENCY_PIN = "1234"  # valid on its own; PIN only requires exactly 4 digits
STORAGE_NAMES = ["Cage", "Shelf"]  # per-location storage names, matches real squad35 topology


@dataclass(frozen=True, slots=True)
class LocationSpec:
    name: str
    multiplier: float


DEFAULT_LOCATIONS = [LocationSpec("BORO", 1.0)]

GENERATION_END_DATE: date = date.today()
