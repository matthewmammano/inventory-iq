"""Build item_profiles.json: run once (or whenever the source catalog/log
changes), not on every generate.py run.

Confidence tiers, per your instruction that real takeout data is "~85%
accurate" for well-sampled items but should NOT be trusted from a handful of
events:
    >=15 real events  -> REAL:     use the real per-item rate/qty directly
    5-14 real events  -> HYBRID:   blend real rate with the category default
    <5 real events    -> ESTIMATED: category/item domain-knowledge default,
                                     capped at ~1/year or rarer

Category defaults and item overrides below are domain knowledge (real-world
EMS/first-aid supply usage patterns), not fit from data; that's the point:
for items too rare to have a reliable sample, a first responder's actual
understanding of how often a tourniquet or an Epi-Pen gets used is a better
estimate than extrapolating from 2 real events over 4 years.

Usage (from repo root):
    python3 scripts/demo_data/build_profiles.py
"""

from __future__ import annotations

import json
from datetime import date

import config as cfg
import numpy as np
import pandas as pd
from profiles import (
    CatalogProfiles,
    DataConfidence,
    ExpirationBehavior,
    ItemGenerationProfile,
    ReorderTriggerProfile,
    TakeoutProfile,
    YearTrend,
)

REAL_EVENTS_THRESHOLD = 15
HYBRID_EVENTS_THRESHOLD = 5
ESTIMATED_MAX_SCANS_PER_DAY = 1 / 300  # ~ once every 10 months, "1/year or rarer"

# ---------------------------------------------------------------- domain-knowledge defaults
# (scans_per_day, qty_mean): deliberately rough; only used when real data is thin.
CATEGORY_DEFAULTS: dict[str, tuple[float, float]] = {
    "Bleeding": (1 / 10, 2.0),
    "Tape": (1 / 20, 1.0),
    "Glucose": (1 / 30, 1.0),
    "Oral Airway": (1 / 45, 1.0),
    "Nasal Airway": (1 / 45, 1.0),
    "Other Airway": (1 / 30, 1.0),
    "Suction": (1 / 30, 1.0),
    "Gloves/Masks": (1 / 5, 2.0),
    "PPE": (1 / 60, 1.0),
    "Disinfection": (1 / 15, 2.0),
    "Immobilization": (1 / 60, 1.0),
    "Splint": (1 / 30, 1.0),
    "Vitals": (1 / 45, 1.0),
    "Medications": (1 / 90, 1.0),
    "CPR": (1 / 120, 1.0),
    "Miscellaneous": (1 / 20, 1.0),
}

# Specific, well-known EMS items where category-level defaults are too generic --
# life-safety/controlled/rare-equipment items with a much better real-world estimate.
ITEM_OVERRIDES: dict[str, tuple[float, float]] = {
    "BVM - Adult": (1 / 45, 1.0),
    "BVM - Child": (1 / 90, 1.0),
    "BVM - Infant": (1 / 180, 1.0),
    "Epi Pen - Adult": (1 / 120, 1.0),
    "Epi Pen - Child": (1 / 240, 1.0),
    "Narcan": (1 / 60, 1.0),
    "Glucose": (1 / 45, 1.0),
    "Albuterol": (1 / 90, 1.0),
    "AED Battery": (1 / 365, 1.0),
    "AED Pad - Adult": (1 / 120, 1.0),
    "AED Pad - Child": (1 / 300, 1.0),
    "ZOLL LifeBand": (1 / 200, 1.0),
    "Tourniquet": (1 / 90, 1.0),
    "Quick Clot": (1 / 120, 1.0),
    "Chest Seal": (1 / 90, 1.0),
    "OB Kit": (1 / 300, 1.0),
    "CPAP": (1 / 200, 1.0),
    "C-Collar - Adult": (1 / 60, 1.0),
    "C-Collar - Child": (1 / 200, 1.0),
    "Mega Mover": (1 / 150, 1.0),
    "Ring Cutter": (1 / 150, 1.0),
    "Seat Belt Cutter": (1 / 150, 1.0),
    "Bulb Syringe": (1 / 150, 1.0),
}


def _confidence_and_takeout(name: str, category: str, per_item_row: dict | None) -> TakeoutProfile:
    n_events = int(per_item_row.get("n_events", 0)) if per_item_row else 0
    real_rate = float(per_item_row["rate_per_day_full_window"]) * per_item_row["op_mix"].get("TAKEOUT", 0) if per_item_row else 0.0
    real_qty = per_item_row["qty_by_op"].get("TAKEOUT", {}).get("mean", 1.0) if per_item_row else 1.0
    real_qty_std = per_item_row["qty_by_op"].get("TAKEOUT", {}).get("std", 0.0) if per_item_row else 0.0
    default_rate, default_qty = ITEM_OVERRIDES.get(name, CATEGORY_DEFAULTS.get(category, (1 / 60, 1.0)))

    if n_events >= REAL_EVENTS_THRESHOLD and real_rate > 0:
        qty_sigma = float(np.clip(real_qty_std / max(real_qty, 0.1), 0.15, 1.5))
        return TakeoutProfile(
            scans_per_day=max(real_rate, 1e-4),
            qty_mean=max(real_qty, 0.1),
            qty_sigma=qty_sigma,
            confidence=DataConfidence.REAL,
            note=f"{n_events} real events, used directly",
        )
    if n_events >= HYBRID_EVENTS_THRESHOLD and real_rate > 0:
        blended_rate = (real_rate + default_rate) / 2
        blended_qty = (real_qty + default_qty) / 2
        return TakeoutProfile(
            scans_per_day=max(blended_rate, 1e-4),
            qty_mean=max(blended_qty, 0.1),
            qty_sigma=0.4,
            confidence=DataConfidence.HYBRID,
            note=f"{n_events} real events, blended with category default",
        )
    rate = min(default_rate, ESTIMATED_MAX_SCANS_PER_DAY) if name not in ITEM_OVERRIDES else default_rate
    return TakeoutProfile(
        scans_per_day=rate,
        qty_mean=default_qty,
        qty_sigma=0.3,
        confidence=DataConfidence.ESTIMATED,
        note=f"only {n_events} real events: domain-knowledge default",
    )


def _corrected_levels(takeout: TakeoutProfile, catalog_batch: int, restock_pool: list[int], count_pool: list[int]) -> tuple[int, int, int]:
    """Item.threshold/reorder_amount (-> catalog min/max/batch) are configured
    settings, not observed reality, and are 2-20x off for roughly half the real
    catalog. Anchor on the item's own assigned usage instead: enough on hand for
    a few weeks of typical use, sized to real restock deliveries when we have
    them, catalog values only as a last-resort floor."""
    daily_usage = takeout.scans_per_day * takeout.qty_mean
    # ~2 weeks of typical use, floor of 2, a rarely-used safety item (e.g. BVM,
    # used every ~45 days) still needs a buffer; "2 weeks of a slow rate" alone
    # rounds to ~1, which is the same "runs to nothing" problem as before.
    usage_based_min = max(round(daily_usage * 14), 2)
    usage_based_batch = int(round(float(np.median(restock_pool)))) if len(restock_pool) >= 3 else max(round(daily_usage * 21), catalog_batch, 1)

    min_quantity = max(usage_based_min, 1)
    batch_size = max(usage_based_batch, 1)
    max_quantity = min_quantity + batch_size

    # Real COUNT history is the most direct evidence of what a shelf ever actually
    # held; when we have it, never let max_quantity run past what real life did
    # (the batch fallback above still leans on catalog reorder_amount for
    # thin-restock items, which is exactly what was 2-20x off in the first place).
    if len(count_pool) >= 3:
        real_ceiling = round(float(np.percentile(count_pool, 95)) * 1.2)
        if max_quantity > real_ceiling:
            max_quantity = max(real_ceiling, min_quantity + 1)
            batch_size = max(max_quantity - min_quantity, 1)
    return min_quantity, max_quantity, batch_size


def _year_trend(log: pd.DataFrame, window_start: date, window_end: date) -> tuple[YearTrend, ...]:
    """Real year-over-year event volume, not an assumed growth curve: 2023-2025
    are full real years; scale each by its ratio to their average. The two
    partial years at the edges of the real dump (2022, 2026) inherit the
    nearest full year's level rather than their own (misleadingly low) partial count."""
    by_year = log.groupby(log["ts"].dt.year).size()
    full_years = [y for y in by_year.index if y not in (by_year.index.min(), by_year.index.max())]
    baseline = by_year.loc[full_years].mean() if full_years else by_year.mean()
    ratios = {int(y): float(by_year[y] / baseline) for y in full_years}

    trend = []
    for year in range(window_start.year, window_end.year + 1):
        if year in ratios:
            trend.append(YearTrend(year=year, multiplier=ratios[year]))
        else:
            nearest = min(ratios, key=lambda y: abs(y - year)) if ratios else None
            trend.append(YearTrend(year=year, multiplier=ratios.get(nearest, 1.0)))
    return tuple(trend)


def main() -> None:
    items = pd.read_csv(cfg.REFERENCE_DIR / "items.csv", dtype={"upc": str})
    log = pd.read_csv(cfg.REFERENCE_DIR / "log.csv", dtype={"upc": str})
    log["ts"] = pd.to_datetime(log["timestamp"])
    log = log.merge(items[["upc", "name"]], on="upc", how="left")
    per_item = {row["name"]: row for row in json.loads((cfg.REFERENCE_DIR / "per_item_params.json").read_text())}

    window_end = cfg.GENERATION_END_DATE
    window_start = date(window_end.year - cfg.YEARS_BACK, window_end.month, window_end.day)

    rng = np.random.default_rng(42)  # fixed seed: rerunning this builder should be reproducible
    profiles: dict[str, ItemGenerationProfile] = {}
    for row in items.itertuples(index=False):
        takeout = _confidence_and_takeout(row.name, row.category, per_item.get(row.name))
        restock_pool = log[(log["name"] == row.name) & (log["operation_type"] == "RESTOCK")]["number"].tolist()
        count_pool = log[(log["name"] == row.name) & (log["operation_type"] == "COUNT")]["number"].tolist()
        min_q, max_q, batch = _corrected_levels(takeout, max(int(row.reorder_amount), 1), restock_pool, count_pool)

        profiles[row.name] = ItemGenerationProfile(
            name=row.name,
            category=row.category,
            takeout=takeout,
            expiration=ExpirationBehavior(tracked=row.name in cfg.EXPIRATION_TRACKED_ITEM_NAMES),
            reorder_trigger=ReorderTriggerProfile(),
            min_quantity=min_q,
            max_quantity=max_q,
            batch_size=batch,
            restock_delivery_days=int(np.clip(round(rng.uniform(3, 14)), 1, 60)),
        )

    catalog = CatalogProfiles(generated_at=date.today(), year_trend=_year_trend(log, window_start, window_end), items=profiles)

    out_path = cfg.REFERENCE_DIR / "item_profiles.json"
    out_path.write_text(catalog.model_dump_json(indent=2))

    by_confidence = pd.Series([p.takeout.confidence for p in profiles.values()]).value_counts()
    print(f"wrote {out_path}: {len(profiles)} items")
    print(by_confidence.to_string())
    print("year trend:", {yt.year: round(yt.multiplier, 2) for yt in catalog.year_trend})


if __name__ == "__main__":
    main()
