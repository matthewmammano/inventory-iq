# Admin Workflows

Expected behavior for scan and admin flows. UI wording rules live in [CONVENTIONS.md](CONVENTIONS.md).

## Guest Scan

1. Choose or confirm current location.
2. Choose source/destination storages when the route needs them.
3. Scan item UPC or search inventory.
4. Submit count, restock, takeout, or transfer action according to route.
5. Write action history and derived balance state together.

Guest capabilities depend on agency settings:

- Count scans require `user_count_allow`.
- Restock scans require `user_restock_allow`.
- Storage direction availability uses `user_access_from` and `user_access_to`.

## Admin Scan

- Admin scan can use expanded route/setup options.
- Admin actions should set `admin_action=True` in inventory history.
- Admin flow may bypass guest permission restrictions but must still validate location, storage, item, and quantity.

## Bulk Actions

- Select a location, route/mode, and target items before editing quantities.
- Save only explicit changes.
- Flash changed versus unchanged outcomes distinctly.
- Keep item selection and grid behavior consistent with existing bulk templates and scripts.
- Bulk quantity validation should highlight invalid cells before save, require counts before stale-item restocks, and keep the final write blocked on backend validation.

## Data (Items, Tags, Notifications)

- One merged Data page lists items, locations, tags, and notification recipients; locations are read-only, the rest support add/edit/delete.
- Items, tags, and notification recipients are created, edited, and deleted one row at a time through per-row modals; see the "Single-Item Modal CRUD" pattern in [CONVENTIONS.md](CONVENTIONS.md). There is no bulk multi-row editing or review-before-save step.
- Preserve soft-delete behavior for items, tags, and recipient rows.
- Keep login email and notification recipient emails separate.
- Data-page screens should use shared Python-defined validation rules for both server validation and generated input attributes.
- Each modal save/delete is a plain form POST followed by a redirect and a flash message naming the specific row affected (e.g. `Item "X" saved.`); failed saves flash short retry guidance instead of raw validation internals.

## History And Reports

- History filters and print views must show the current location scope.
- Inventory count reports compare item counts by location and storage.
- Report emails go to configured notification recipients, not automatically to the account login email.

## UPC Review

- Unknown UPC scans are held for admin classification.
- The Pending UPCs page always shows the full Pending and Ignored lists together; there is no single-review or "return to tasks" mode. A `focus_upc` query param only highlights a row, it never hides the rest.
- Online lookup suggestions are uncertain and must be worded as assistance, not truth.
- Linking a UPC should preserve agency-level uniqueness rules from [DATA_MODEL.md](DATA_MODEL.md).
- UPC entry should validate length, digits, and check digit in the browser before submit when practical, then re-check the same rules in Python.

## Restock And Forecasting

- Restock values are estimates from recent usage and current balance data.
- UI text must tell admins to review current stock before ordering.
- Trend logic belongs in `app/prediction/`; restock/admin presentation belongs in `app/inventory/`.
- Before an item has a trained usage trend, the Restock page falls back to `items.prior_daily_usage` when set (a one-time estimate provided during setup, not user-editable); Confidence stays blank for these estimated rows so admins can tell a rough estimate apart from a trained trend.
