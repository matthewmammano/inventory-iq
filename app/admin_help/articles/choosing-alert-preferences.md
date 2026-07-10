---
id: choosing-alert-preferences
title: Choosing Your Alert And Summary Preferences
summary: Set per-recipient alert types, summary emails, alert frequency, quiet hours, and location filters.
tags: Emails, Settings
---

## Where This Lives

Open Data and go to the Notifications tab. Every row is one notification recipient (an email address, not necessarily the squad login email), with its own settings. Add Notification creates a new recipient; the edit icon on a row opens the same fields to change or remove it.

## Per-Recipient Settings

- **Locations** limits which locations this recipient hears about. Leave it empty to receive alerts for every location.
- **Alert Frequency** controls how often stock and activity alerts are batched into an email: Instant (checked every 10 minutes), Hourly, or Daily. A recipient never gets more than one alert email per chosen interval, even if several alerts became due within it.
- **Quiet Hours** is an optional start and end time. Alerts due during that window wait until quiet hours end instead of sending immediately; they are not skipped.
- **Alerts** checkboxes choose which alert types this recipient receives: Stockout, Pred Stockout, Low, Pred Low, Stale Count, Rare Takeout, Count, Restock, Takeout, Transfer, Expired, Expiring, and Exp Count.
- **Summaries** checkboxes choose which recap emails this recipient receives: Daily, Weekly, Monthly, Yearly.

## Picking What To Turn On

Stockout, Low Stock, and their predicted versions are the highest-value alerts for most recipients, since they point at real ordering decisions. Count, Restock, Takeout, and Transfer are activity notices, useful for an owner who wants a live feed of scanning but noisy for a recipient who only cares about problems. Rare Takeout and Stale Count call out unusual patterns worth a second look rather than urgent action.

> A recipient's Alert Frequency and Quiet Hours apply to every alert type they have checked. There is no way to make one alert type instant and another daily for the same recipient — use a second recipient row with the same email's alternate address, or split by which alert types matter to each person, if you need different timing.

## Related

See [Email Types And Reports](email-types-and-reports) for the difference between alert emails, summary emails, and report emails, and [Why Am I Not Receiving Emails?](why-not-receiving-emails) if a recipient should be getting something and is not.
