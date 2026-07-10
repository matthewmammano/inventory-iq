---
id: admin-settings
title: Admin Settings
summary: Understand the squad image, admin PIN, guest permissions, default location, and warning thresholds.
tags: Settings, Admins
---

## Where To Go

Open **Settings** from the Admin Panel.

## What You Can Change Here

- **Squad Image** changes the header logo shown throughout the app for this squad.
- **Admin PIN** is the code that unlocks admin pages from the guest screen. See [Account Security](account-security-and-access) for how the PIN session behaves.
- **Guest Permissions** decide which stock actions (Count, Restock, Takeout, Transfer) a non-admin scanner is allowed to use, and in which direction. See [Admin Stock Actions Vs Guest Scans](admin-vs-guest-stock-actions).
- **Device Default Location** saves the usual location a device starts from, so scanners on a fixed device do not have to pick a location every time.
- **Expiration Warning Days** sets the squad-wide default for how many days before expiration a tracked item counts as "expiring soon." Individual items can override this — see [Tracking Expiration Dates](tracking-expiration-dates).

## What You Cannot Change Here

> Squad name, account login email, locations, and storages cannot be edited from this page. Contact support to change these, since they affect login, existing history, and scan routes across the whole squad.

## Recommended Save Pattern

1. Change one group of settings at a time when possible, so it is obvious what caused any behavior change.
2. Review the confirmation text before saving.
3. If you changed guest permissions, test the affected action from a guest scan afterward to confirm it behaves as expected.
