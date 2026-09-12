---
id: add-edit-delete-items
title: Add, Edit, Or Delete Items
summary: Manage item names, UPCs, tags, thresholds, and active status from the Data page.
tags: Items, Barcodes
---

## Where To Go

Open **Data** from the Admin Panel, then the **Items** tab. Click the edit icon on a row to open that item's edit modal, or **Add Item** to create a new one. The same modal handles editing and deleting; there is no separate delete screen.

## What You Can Set

- **Name** is what users see while scanning and on reports. Keep it recognizable at a glance.
- **Primary UPC and Secondary UPCs** control which scanned barcodes match this item. See [Linking New Barcodes](linking-new-barcodes) for adding an extra one later.
- **Tags** group items for searching and review.
- **Min Quantity / Max Quantity** define low-stock and overstock thresholds used by Restock and Inventory Levels.
- **Order Size** and **Lead Time Override** feed restock planning. Leaving Lead Time Override blank uses the squad default.
- **Track Expiration Dates** turns on per-scan expiration entry for this item. See [Tracking Expiration Dates](tracking-expiration-dates).

## Safe Edit Pattern

1. Open the item and change only what needs to change.
2. Save.
3. If the name, primary UPC, or shelf organization changed, reprint labels (see [Printing Labels](printing-labels)) so the physical shelf card matches.

## Delete Behavior

> Deleting an item marks it inactive once you save; it does not erase it. Existing History rows for that item stay exactly as they are, so past audits still make sense. A deleted item drops out of scanning, Restock, and Inventory Levels. If its old barcode gets scanned again later, Inventory IQ will not match it to the deleted item; it shows up as an unknown barcode instead. See [Handling Unknown Barcodes](handling-unknown-barcodes) if that item comes back into use.
