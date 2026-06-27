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

## View/Edit Data

- Edit active items, tags, locations/storages, and notification recipients through review-before-save screens.
- Preserve soft-delete behavior for items and recipient rows.
- Keep login email and notification recipient emails separate.
- New item management must not ship partial behavior; see [TODO.md](TODO.md).

## History And Reports

- History filters and print views must show the current location scope.
- Inventory count reports compare item counts by location and storage.
- Report emails go to configured notification recipients, not automatically to the account login email.

## UPC Review

- Unknown UPC scans are held for admin classification.
- Online lookup suggestions are uncertain and must be worded as assistance, not truth.
- Linking a UPC should preserve agency-level uniqueness rules from [DATA_MODEL.md](DATA_MODEL.md).

## Restock And Forecasting

- Restock values are estimates from recent usage and current balance data.
- UI text must tell admins to review current stock before ordering.
- Trend logic belongs in `app/prediction/`; restock/admin presentation belongs in `app/inventory/`.
