# Repo Conventions

Inventory IQ-specific conventions only. Generic engineering rules live in [../AGENTS.md](../AGENTS.md). Architecture, data, deploy, and observability facts live in their dedicated docs.

## UI Text

- Visible labels carry required meaning; tooltips are optional explanation only.
- Prefer specific actions: `Save Changes`, `Back to Admin`, `Back to Bulk Action`, `Back to Labels`, `Back to Scan`.
- Prefer specific continuations: `Continue to Item Scan`, `Continue to Bulk Grid`, `Continue to Storage Selection`.
- Avoid vague labels such as `Go`, `Submit`, `Save`, `Back`, or `Continue` when context matters.
- Placeholders are examples or formats only: `12-digit UPC`, `Search items or UPCs`, `Scan item barcode or search inventory`, `name@example.com`, `https://example.com/image.jpg`, `e.g. each`, `e.g. 7`.
- Do not use placeholders as the only label or instruction.
- Helper text explains consequences, rules, or constraints before the user decides.
- Tooltips are for optional explanation on dense tables, icon-only actions, calculated values, or advanced concepts.
- Do not add tooltips to normal buttons like Save, Back, Continue, Add, Link, Print, or Cancel.

## Flash Messages

- `success`: requested action completed, e.g. `Settings saved.`
- `info`: neutral outcome or nothing changed, e.g. `No changes entered.`
- `warning`: user-fixable issue, e.g. `Select at least one item.`
- `error`: action failed, e.g. `Settings could not be saved. Try again.`
- Keep flashes short, plain, and actionable.
- Distinguish changed versus unchanged saves: `Saved 3 row(s).` versus `No changes entered.`
- Do not expose exception names, SQL details, provider responses, secrets, or tracebacks.

## Templates And Modals

- Use `<strong>` for important dynamic non-item values such as selected location, route, support phone, or print scope.
- Use `bold_item_name` only for item names.
- Preserve edit-data/settings review modal fields: `data-label`, `data-original`, and `data-review-text`.
- Delete toggles must communicate the real behavior: marked now, hidden after saving.
- Cap review modal lists and summarize overflow with `...and N more changes`.

## Notification Emails

- `agencies.email` is the login, password reset, and admin identity email.
- `agency_emails.email` is for alert/report recipients shown in View/Edit Notifications and used for alert/report delivery.
- Do not auto-copy the account login email into notification recipients unless the product explicitly adds that action.

## Inventory Alerts And History UI

- History filters and print views must show the current location scope.
- Alert and restock projections must be phrased as estimates, not guarantees.
- Preferred restock estimate wording: `Estimated from recent usage trends. Review current stock before ordering.`
- Online UPC lookup suggestions are uncertain and must be worded as assistance, not truth.
