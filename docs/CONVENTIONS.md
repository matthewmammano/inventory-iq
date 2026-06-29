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

## Icons

- Preferred icon source for this project: [Icons8 Material Outlined](https://icons8.com/icons/all--style-material-outlined).
- Use icons sparingly and only when they clarify dense UI, support compact actions, or match existing project patterns.

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

## Validation Pattern

- Python owns validation rules. Prefer reusable typed aliases in `app/shared/validation_types.py` backed by helpers in `app/shared/validators.py`.
- Reuse those aliases in schemas and service-layer form models before adding one-off `field_validator` logic.
- When an HTML input needs matching browser validation, generate attributes with `validation_attrs(...)` instead of hand-writing `type`, `pattern`, `maxlength`, or duplicate rule strings in templates.
- Keep frontend validation messages concise and user-facing. Do not surface raw Pydantic errors, exception names, or internal field paths in flashes.
- Use frontend validation for immediate feedback, highlight state, grouped required choices, paired fields, and submit blocking. Backend validation still decides whether the write is valid.
- If a rule has cross-field behavior such as paired quiet hours, min/max comparisons, or required-if-present logic, keep the canonical rule in Python and mirror only the UI behavior needed for early feedback.
- When parsing form posts, preserve the real target type. Empty checkbox lists that represent `list[int]` should stay empty lists, while optional scoped filters may still normalize to `None`.
- Shared validation JS belongs in `app/static/js/form-validation.js`. Page scripts may integrate with it, but should avoid re-implementing generic validators like email, PIN, UPC, quantity, or password checks.

## Notification Emails

- `agencies.email` is the login, password reset, and admin identity email.
- `agency_emails.email` is for alert/report recipients shown in View/Edit Notifications and used for alert/report delivery.
- Do not auto-copy the account login email into notification recipients unless the product explicitly adds that action.

## Inventory Alerts And History UI

- History filters and print views must show the current location scope.
- Alert and restock projections must be phrased as estimates, not guarantees.
- Preferred restock estimate wording: `Estimated from recent usage trends. Review current stock before ordering.`
- Online UPC lookup suggestions are uncertain and must be worded as assistance, not truth.
- Show timestamps in the user's or agency's local timezone in the UI, but keep stored timestamps in the backend/database as UTC or UTC-naive values.
