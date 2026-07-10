---
id: email-types-and-reports
title: Email Types And Reports
summary: Understand alert emails, summary emails, and report emails, and where each is sent from.
tags: Emails, Reports
---

## The Main Idea

Inventory IQ sends email for two different reasons: automatic notifications, based on saved preferences, and admin-requested reports, sent only when an admin asks for one. Every email carries the sender name **Inventory IQ** and a recognizable subject prefix — see [Marking Inventory IQ Emails As Important, Not Spam](marking-emails-as-not-spam) for the exact patterns.

## Alert Emails

Alert emails point out a stock condition or scan activity worth reviewing: Stockout, Low Stock, their predicted versions, Stale Count, Rare Takeout, Count/Restock/Takeout/Transfer activity, Expired, Expiring Soon, and Exp Count Needed. An alert firing does not always mean something is wrong — it means Inventory IQ found something worth a look. Which alert types a recipient gets, and how often, is set per recipient — see [Choosing Your Alert And Summary Preferences](choosing-alert-preferences).

## Summary Emails

Summary emails group recent activity into one recap: Daily, Weekly, Monthly, or Yearly, per recipient preference. Useful for someone who wants the bigger picture instead of one email per event.

## Report Emails

Report emails are sent manually, from a report page (**Inventory Levels**, **Restock**, or **View History**), by clicking Email Report and choosing recipients. They are never sent automatically just because the page exists — no recipient chosen means no email sent. Each includes a CSV spreadsheet-style attachment scoped to what was on screen (location, date range, or both).
