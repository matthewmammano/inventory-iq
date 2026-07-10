---
id: understanding-restock-page
title: Understanding The Restock Page
summary: Read restock estimates, current stock, confidence, and ordering signals correctly.
tags: Restock, Predictions
---

## What The Restock Page Is

**Restock**, in the Admin Panel, helps you decide what may need ordering or review. It combines current inventory levels with recent usage estimates.

## How To Read It

- **Current stock** is what Inventory IQ believes is on hand right now.
- **Minimum quantity** is the point where stock should be watched closely.
- **Estimated usage** comes from recent scan history, once enough of it exists to train a trend.
- **Confidence** shows a percentage once a trend has trained; it shows blank rather than 0% for a new or thin-history item, which is falling back to the one-time setup estimate instead. See [How Predictions Work](how-predictions-work).
- **Projected warnings** (predicted low stock / predicted stockout) only appear once the item is within its lead time of running out, not as soon as usage starts trending down.

## The Most Important Rule

> Estimated from recent usage trends. Review current stock before ordering. A recent missed scan, unusual event, or wrong Count can shift the recommendation.

## What To Do With A Suspicious Estimate

1. Check the current stock in person if possible.
2. Review recent [History](review-inventory-history) for that item.
3. Correct the quantity with Count if it is wrong.
4. Record new stock with Restock once it arrives.
