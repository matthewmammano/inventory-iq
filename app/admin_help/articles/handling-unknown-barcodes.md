---
id: handling-unknown-barcodes
title: Handling Unknown Barcodes
summary: Review UPCs that were scanned but not recognized, from the Pending UPCs page.
tags: Barcodes, Scanning
---

## What Unknown Means

An unknown barcode is a UPC that someone scanned but Inventory IQ could not match to an active item. It does not always mean the item is new — it may be a new package or an alternate barcode for an existing item.

## Review Flow

1. Open **Pending UPCs** from the Admin Panel, or click "Review Barcodes" from a Pending Tasks row.
2. Review the UPC and any online lookup suggestion shown.
3. Search for the correct existing item.
4. Link the UPC to that item only when it should count as the same inventory — see [Linking New Barcodes](linking-new-barcodes).
5. Leave it unresolved (Ignore) if you are not sure yet; it will stay on this page until you decide.

> The Pending UPCs page always shows every pending and ignored barcode together — it does not narrow down to just one when you arrive from a Pending Tasks link. Use the search or the highlighted row to find the one you came to review.

## Example

If a replacement package scans differently but should count as the same inventory item, link the new UPC to that item rather than creating a duplicate.

## Why This Matters

Correct barcode links keep future scanning fast and accurate. A wrong link opens the wrong item, which can damage that item's counts and history.
