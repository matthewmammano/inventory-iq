---
id: marking-emails-as-not-spam
title: Marking Inventory IQ Emails As Important, Not Spam
summary: Recognize real Inventory IQ emails and stop your inbox from filing them as spam.
tags: Emails, Settings
---

## Why This Happens

Email providers watch for patterns they associate with bulk or automated mail: a sender you have never replied to, a subject line that repeats often, or a message sent to many people at once. Inventory IQ's alert, summary, and report emails can look like that pattern even though every one of them is a real, requested notification. Telling your email provider to trust the sender fixes this permanently, so you stop losing time checking a spam folder.

## What To Look For

Every Inventory IQ email displays the sender name **Inventory IQ**. The subject line always starts with one of these patterns, so you can recognize a real message at a glance and safely search your spam folder for it:

- Alert emails start with a colored square and severity, for example `🟥 [CRITICAL]`, `🟧 [HIGH]`, `🟨 [MEDIUM]`, `🟩 [LOW]`, or `🟦 [INFO]`, followed by "Inventory Alerts" and your squad name.
- Report emails start with `⬜ [REPORT]`, followed by the report name (Inventory Counts, History Logs, or Restock Estimates) and your squad name.
- Summary emails are titled `Inventory Daily Summary`, `Inventory Weekly Summary`, `Inventory Monthly Summary`, or `Inventory Yearly Summary`.

> Do not allowlist by subject line alone, since anyone could send a lookalike subject. Allowlist the sender's actual email address, which you can only see by opening one real Inventory IQ email you already received and checking who it is from.

## Gmail: Stop Filing Inventory IQ In Spam

1. Open one Inventory IQ email. If it is already in Spam, open it from there.
2. Click the three-dot menu in the top right of the open message.
3. Choose "Add [sender] to Contacts list." If the message is in Spam, also click "Report not spam" at the top of the message.
4. For a permanent rule, click the search box, type `from:` followed by the sender's address, click the filter (sliders) icon on the right side of the search box, then click "Create filter."
5. Check "Never send it to Spam," and optionally "Always mark it as important," then click "Create filter."

## Outlook Or Microsoft 365: Add A Safe Sender

1. Open one Inventory IQ email.
2. Right-click the sender name, or open the message and click the three-dot menu.
3. Choose "Add to Safe Senders" (web) or "Junk" then "Never Block Sender" (desktop app).
4. If the message already landed in Junk Email, open the Junk Email folder, right-click the message, and choose "Not Junk" as well.

## Other Providers

Every major provider (Yahoo, iCloud, Apple Mail, and company-managed mail like Microsoft 365 admin filtering) has an equivalent "Add to contacts," "Not spam," or "Safe senders" action. If your company IT department manages email filtering centrally, individual allowlisting may not be enough. Send them the sender's exact email address from a received message and ask for it to be added to the organization's allow list.

## If You Still Do Not See Expected Emails

Allowlisting only helps once Inventory IQ has actually sent an email. If you never receive one at all, even in spam, the cause is usually recipient setup rather than spam filtering. See [Why Am I Not Receiving Emails?](why-not-receiving-emails) to check recipients, alert preferences, and quiet hours first.
