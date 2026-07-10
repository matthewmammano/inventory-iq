---
id: how-predictions-work
title: How Predictions Work
summary: Predictions use recent scan history and are only estimates, not guarantees.
tags: Predictions, Restock
---

## What A Prediction Means

A prediction is Inventory IQ's best estimate of future inventory need. It looks at recent scan history and current balances to estimate whether an item may run low or need restocking soon.

> Estimated from recent usage trends. Review current stock before ordering. A prediction is not a promise, a purchase order, or proof the shelf is empty — it is a planning signal.

## Why A Predicted Alert Sometimes Feels Late

Predicted Stockout and Predicted Low Stock alerts only appear once an item is within its lead time of running out — not as soon as a downward trend exists. If an item's lead time is 3 days, the predicted alert will not fire until the estimate crosses that 3-day window, even if the trend has been declining for weeks. This is intentional, so predicted alerts line up with when ordering actually needs to happen, but it means a slow, steady decline can look like it "suddenly" triggers an alert.

## Why Confidence Is Sometimes Blank

A new item, or one without enough recent scan history, has not trained a usage trend yet. Until it does, Restock falls back to the one-time usage estimate entered during setup and shows no confidence percentage rather than a misleading 0%. Confidence appears once enough real Count/Restock/Takeout history has accumulated to train a trend.

## What Makes Predictions Better

Predictions improve when scan history matches real activity:

- Use **Count** to correct current stock, not to hide a delivery.
- Use **Restock** when new stock arrives.
- Use **Takeout** when stock leaves inventory.
- Use **Transfer** when stock moves between places.

## What Makes Predictions Worse

- Restock entered as Count hides the real delivery from restock history.
- Missing Takeout scans make usage look lower than it really is.
- Wrong Counts throw off the current balance the whole estimate is built on.
- One-time events (a bulk giveaway, a damaged case) can make recent usage look unusual for a while.
- Very high daily usage on one item is capped at 99/day internally, so an extremely fast-moving item's trend can show as understated with no on-screen indicator that it happened.
