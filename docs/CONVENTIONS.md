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

- Python owns validation. Add reusable rules in `app/shared/validation_types.py` as `FieldRuleName` + `FieldSpec`, backed by Pydantic aliases and helpers in `app/shared/validators.py`; reuse those aliases in form/service models before adding one-off validators.
- Templates get frontend attributes only through `validation_attrs(...)`; do not hand-write duplicate `type`, `pattern`, `maxlength`, `min`, rule names, or user-facing rule messages.
- Shared browser validation lives in `app/static/js/form-validation.js` as `window.InventoryFormValidation`; page scripts may call `validateForm`, `validateField`, or `setExternalError`, but must not reimplement generic email, PIN, password, UPC, quantity, date, color, image, paired-field, comparison, or required-choice logic.
- Use inline `.field-hint` messages and `.invalid` styling for user-fixable field errors. Place hints above dense inputs using the shared wrappers/patterns, never in a way that widens table columns or settings rows.
- Default to live validation for edit/admin forms so invalid values show immediately. Use `data-validation-live="submit"` for auth/simple selection flows where errors should appear only after a submit attempt. Use `data-validation-submit="manual"` only when a page script owns a review modal, scanner flow, or custom submit sequence.
- Keep backend validation authoritative and safe. Frontend validation is for fast feedback only; backend failures should return concise field errors when useful, or one generic user message plus safe Loguru context when the issue is unexpected.
- Avoid browser-native validation popups. Forms using shared validation should rely on `novalidate` or the shared script's `form.noValidate = true`.
- Cross-field rules such as quiet-hour pairs, min/max comparisons, required-if-present fields, and count-before-restock behavior keep the canonical rule in Python and mirror only the UI behavior needed for early feedback.
- When parsing form posts, preserve the real target type. Empty checkbox lists that represent `list[int]` stay empty lists, while optional scoped filters may still normalize to `None`.

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
