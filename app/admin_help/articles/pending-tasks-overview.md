---
id: pending-tasks-overview
title: Understanding Pending Tasks
summary: Read the Pending Tasks badge and clear missing dates, stale counts, and unlinked barcodes.
tags: Admins, Barcodes
---

## Where It Shows Up

The Admin Panel header shows a "Pending Tasks" button with a number badge whenever there is unresolved admin work for your squad. The badge shows "9" when there are more than nine pending items, so treat a "9" badge as "at least nine," not exactly nine. Opening Pending Tasks always lists everything currently unresolved, grouped by task type.

## What Can Appear There

- **Fix Missing Expiration Dates**: tracked items have on-hand quantity with no expiration date recorded. See [Tracking Expiration Dates](tracking-expiration-dates).
- **Recount Stale Inventory Quantities**: a location has items that have not been counted recently enough to trust the current number. Opening "Open Recount" takes you straight to Bulk Action for that location with the stale items pre-selected.
- **Review New Barcodes Requested**: a scanned UPC did not match any active item. See [Handling Unknown Barcodes](handling-unknown-barcodes).

Only task types with at least one item show a row; an empty Pending Tasks page means there is nothing left to review.

## Clearing A Task

Each row's button goes directly to the right page to resolve it: expiration entry, bulk recount, or barcode review. There is no way to dismiss a task without actually resolving the underlying item, which keeps the badge count meaningful instead of becoming a to-do list you can check off without doing the work.
