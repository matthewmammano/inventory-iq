---
id: dashboard-overview
title: Understanding The Admin Dashboard
summary: Read the Needs Attention counts and open the page that clears each one.
tags: Admins, Barcodes
---

## Where It Shows Up

The Admin Dashboard is the first screen you see after entering your admin PIN. The top row, "Needs Attention", shows one tile for every kind of problem Inventory IQ watches for, with how many items are affected right now. Anything sitting at zero slides to the end of the row, so whatever needs you most is always on the left.

## What Can Appear There

- **Out of Stock** and **Running Low**: quantity on hand has hit zero or dropped under the reorder amount you set. Both open the Restock Report.
- **Will Run Out** and **Will Run Low**: nothing is wrong yet, but recent use says it will be soon.
- **Expired** and **Expiring Soon**: the expiration date has passed or is close. See [Tracking Expiration Dates](tracking-expiration-dates).
- **Missing a Date**: a tracked item has stock on hand with no expiration date recorded.
- **New Barcode**: a scanned UPC did not match any active item. See [Handling Unknown Barcodes](handling-unknown-barcodes).
- **Not Counted Lately**: a location has items nobody has counted recently enough to trust.
- **Unusual Takeout**: something came off the shelf after a long quiet stretch.

## Clearing A Tile

Tap a tile and it opens the page that fixes it. A count only drops when the underlying problem is actually solved: stock gets restocked, a date gets entered, a barcode gets linked or ignored. There is no way to dismiss a tile without doing the work, which keeps the numbers worth trusting.

## Below The Tiles

The "Go To" section underneath holds every admin page: Scan Items, Restock Report, Stock Levels, History, Bulk Edit, Print Labels, Unknown Barcodes, Items & Tags, Settings, and Help.
