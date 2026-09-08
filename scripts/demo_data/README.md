# Demo data generator

Builds a synthetic-but-realistic demo DB by replaying events through the real
Flask service layer (`inventory_operation`, `save_bulk_edit`, etc.) -- not
raw DB inserts. Any event that fails real validation is skipped, not forced in.

## Run it

```bash
pip install -r scripts/demo_data/requirements.txt

DEV_CLOCK_ENABLED=true DATABASE_URL=sqlite:///instance/inventory_iq.db \
    python3 scripts/demo_data/generate.py \
    --location "POINT BORO:1.0" --location "POINT BEACH:0.6" --seed 42
```

- `--location NAME:MULTIPLIER` (repeatable) -- `1.0` = real observed volume.
- `--seed` -- deterministic; same seed + args = same DB.
- `--accuracy real|ideal` -- `ideal` drops guest scan errors near zero, to
  compare against better scanning discipline.
- `DEV_CLOCK_ENABLED=true` is required (drives `app/shared/clock.py` so real
  freshness checks evaluate against simulated historical time).

Creates agency `Squad 35 Demo`, password + PIN `1234`. The password is set
via a direct hash (bypasses the app's real strength check, on purpose, for
this one demo field) -- everything else goes through real validation. **Restart
`flask run` after regenerating** -- it holds stale connections to the old file.

## Files

| File | Role |
|---|---|
| `config.py` | every tunable constant |
| `setup.py` | creates Agency/Location/Storage/Item (plain ORM -- `@validates` still fires) |
| `planner.py` | builds the event timeline, no DB access |
| `replay.py` | the only file that touches the DB -- replays events through real service calls |
| `generate.py` | CLI: setup → plan → replay → rebuild |
| `reference/` | real POINT BORO historical data the whole model is calibrated on |

## How it models a squad

- **Guest stream**: TAKEOUT/TRANSFER, bootstrapped per-item from real
  quantities/rates, with real scan-error rates layered on (forgot/under/over).
  ~95% guest, ~5% admin.
- **Admin audit stream**: full-location COUNT + optional RESTOCK, bundled in
  one session (a real RESTOCK requires a fresh COUNT first). COUNT ceilings
  and RESTOCK sizes are bootstrapped from each item's real observed
  quantities (`reference/log.csv`), not from its configured
  `threshold`/`reorder_amount` -- those settings are frequently 2-20x off
  from anything ever physically counted.

## Known gaps

- Per-storage split (Cage vs. Shelf) uses the same combined real
  distribution -- doesn't model them diverging systematically.
- No modeled expired-stock disposal outside normal TAKEOUT.
