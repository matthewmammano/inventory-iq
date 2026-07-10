---
id: tracking-expiration-dates
title: Tracking Expiration Dates
summary: Turn on expiration tracking per item, enter dates during scans, and clear the Fix Dates task.
tags: Items, Restock, Settings
---

## Turning Tracking On For An Item

Expiration tracking is off by default and set per item, not squad-wide. Open the item in Data, check "Track Expiration Dates," and save. Once enabled, Restock, Takeout, and Count scans for that item will ask for expiration dates instead of just a quantity.

## Entering Dates During A Scan

When you Restock a tracked item, enter the expiration date printed on the new stock. When you Takeout a tracked item, choose which expiration date the removed stock came from, starting with the earliest date so older stock gets used first. Quantity steppers let you split one scan across several expiration dates when a shelf has mixed batches. If the exact date is not listed and cannot be entered, use "Other / Not Listed" rather than guessing a date.

> Enter dates for the quantity you are actually recording. If the count itself looks wrong, use Count to correct it instead of forcing expiration numbers to add up.

## Fix Missing Expiration Dates

If a tracked item already has stock on hand with no expiration date recorded, Pending Tasks shows a "Fix Missing Expiration Dates" row with a count of item/storage pairs that need it. Opening "Fix Dates" from there lets you assign dates to existing quantity directly, without creating a new Count, Restock, or Takeout action.

## Warning Alerts

Two alert types come from expiration tracking:

- **Expiring Soon** fires when tracked stock is within its warning window, which defaults to your squad's Expiration Warning Days setting (Settings page) unless the item has its own Expiration Warning Override (Data page) set instead.
- **Expired** fires once tracked stock's date has passed.

Both alerts follow your notification preferences the same way stock alerts do. See [Choosing Your Alert And Summary Preferences](choosing-alert-preferences) to control which recipients get them.
