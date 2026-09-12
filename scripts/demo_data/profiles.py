"""Pydantic schema for the per-item generation profile: the single source of
truth for both the real Item schema fields (setup.py writes these to the DB)
and the generation behavior (planner.py samples from these). Built once by
build_profiles.py, stored as reference/item_profiles.json, and just loaded
(not recomputed) on every generate.py run.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DataConfidence(StrEnum):
    """How this item's takeout numbers were derived: kept on the record so a
    future reviewer can tell "real data" apart from "domain-knowledge guess"
    at a glance, instead of every item looking equally authoritative."""

    REAL = "real"  # >=15 real events: real per-item rate/qty trusted directly
    HYBRID = "hybrid"  # 5-14 real events: real signal blended with a category default
    ESTIMATED = "estimated"  # <5 real events: domain-knowledge default, rate capped low


class TakeoutProfile(BaseModel):
    """How often and how much this item gets scanned out. This is the only
    thing modeled with per-event granularity; COUNT/RESTOCK are derived from
    it plus the item's own (corrected) min/max/batch fields."""

    model_config = ConfigDict(frozen=True)

    scans_per_day: float = Field(gt=0, le=20, description="mean rate of individual takeout scans/day")
    qty_mean: float = Field(gt=0, le=2000, description="mean quantity per scan")
    qty_sigma: float = Field(ge=0.1, le=1.5, description="lognormal spread per scan")
    confidence: DataConfidence
    note: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _low_confidence_stays_plausible(self) -> "TakeoutProfile":
        # Generic category fallbacks (no real signal, no specific judgment call) must
        # stay rare (~1/year or less); a specific item override is allowed to say
        # otherwise (e.g. C-Collar - Adult genuinely isn't a once-a-year item) but
        # everything estimated still gets a sanity ceiling against real mistakes.
        if self.confidence is DataConfidence.ESTIMATED and self.scans_per_day > 1 / 20:
            raise ValueError("estimated items should not exceed ~once every 3 weeks without real data to back it up")
        return self


class ExpirationBehavior(BaseModel):
    """FEFO (first-expired-first-out) pick behavior. Fixed rates, not fit per
    item: these describe a human habit, not this item's physical reality."""

    model_config = ConfigDict(frozen=True)

    tracked: bool
    fefo_compliance_rate: float = Field(default=0.95, ge=0, le=1)
    wrong_pick_rate: float = Field(default=0.03, ge=0, le=1)
    forgot_log_rate: float = Field(default=0.02, ge=0, le=1)

    @model_validator(mode="after")
    def _rates_sum_to_one(self) -> "ExpirationBehavior":
        total = self.fefo_compliance_rate + self.wrong_pick_rate + self.forgot_log_rate
        if self.tracked and abs(total - 1.0) > 1e-6:
            raise ValueError(f"FEFO pick rates must sum to 1.0, got {total}")
        return self


class ReorderTriggerProfile(BaseModel):
    """Staff don't restock at exactly Item.min_quantity every single time --
    this is the variability around it, not a replacement for it."""

    model_config = ConfigDict(frozen=True)

    center_ratio: float = Field(default=1.0, gt=0, le=2, description="trigger center as a multiple of Item.min_quantity")
    spread_ratio: float = Field(default=0.2, ge=0, le=1)


class ItemGenerationProfile(BaseModel):
    """Everything the generator needs for one item. min_quantity/max_quantity/
    batch_size/restock_delivery_days are written to the real Item row AS WELL
    as used for generation: one corrected value, not two systems that can
    disagree."""

    model_config = ConfigDict(frozen=True)

    name: str
    category: str
    takeout: TakeoutProfile
    expiration: ExpirationBehavior
    reorder_trigger: ReorderTriggerProfile = ReorderTriggerProfile()

    min_quantity: int = Field(gt=0)
    max_quantity: int = Field(gt=0)
    batch_size: int = Field(gt=0)
    restock_delivery_days: int = Field(gt=0, le=60)

    @model_validator(mode="after")
    def _max_above_min(self) -> "ItemGenerationProfile":
        if self.max_quantity <= self.min_quantity:
            raise ValueError(f"{self.name}: max_quantity ({self.max_quantity}) must exceed min_quantity ({self.min_quantity})")
        return self


class YearTrend(BaseModel):
    model_config = ConfigDict(frozen=True)

    year: int
    multiplier: float = Field(gt=0, le=3)


class CatalogProfiles(BaseModel):
    """The full, versioned, human-reviewable parameter set. Regenerate with
    build_profiles.py when the source catalog/log changes; every other script
    just loads this file."""

    generated_at: date
    year_trend: tuple[YearTrend, ...]
    items: dict[str, ItemGenerationProfile]

    def year_multiplier(self, year: int) -> float:
        return next((yt.multiplier for yt in self.year_trend if yt.year == year), 1.0)
