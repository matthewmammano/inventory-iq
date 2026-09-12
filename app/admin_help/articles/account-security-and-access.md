---
id: account-security-and-access
title: Account Security: Login, Passwords, PIN, And Lockouts
summary: Password rules, resetting a forgotten password, admin PIN session timeout, and rate-limit lockouts.
tags: Settings, Admins
---

## Password Requirements

A password must be at least 10 characters and include a letter, a number, and a symbol. The login and reset-password forms only tell you which of these you are missing after you submit, so if a save is rejected, check for all four before trying again.

## Resetting A Forgotten Password

1. From the login page, choose the forgot-password link and enter the squad's account email.
2. Inventory IQ emails a 6-digit reset PIN to that address. It expires 15 minutes after it is sent, so request a fresh one if too much time passes.
3. Enter the PIN and a new password meeting the requirements above.

If the reset PIN email does not arrive, check spam first (see [Marking Inventory IQ Emails As Important, Not Spam](marking-emails-as-not-spam)), since password reset mail is sent from the same address as alerts and reports.

## Admin PIN Vs Account Login

Logging in with your email and password gets you into the squad's guest scanning screens. Admin pages are a separate layer behind the squad's admin PIN, entered from the guest screen. This second layer exists so a shared scanning device can stay logged into the squad without every guest scanner also having admin access.

## Admin Sessions Time Out After 2 Hours

Entering the admin PIN unlocks admin pages for 2 hours of activity on that device. After 2 hours of no admin activity, Inventory IQ signs the device back out of admin pages automatically and flashes "Admin session expired. Enter your PIN again." Guest scanning is unaffected. Only admin pages ask for the PIN again. This is expected behavior, not an error, and it protects a device that gets left unlocked in a back room.

## "Too Many Attempts" Lockouts

Login, forgot-password, reset-password, and admin PIN entry are all limited to 10 attempts per minute and 50 per hour from the same network address. Going over either limit shows a "Too Many Attempts" page instead of the normal form. This is a defense against repeated guessing, not a sign anything is broken; wait a minute (or up to an hour, if the hourly limit was hit) and try again. If this happens during normal use, it usually means a typo is being retried quickly; slow down and re-check the email, password, or PIN before the next attempt.
