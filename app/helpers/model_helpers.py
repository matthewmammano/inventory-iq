def get_or_create_qty_row(db_session, user_id, item_id, location_id):
    """Get or create ItemLocationQuantities row."""
    from app.inventory.models import ItemLocationQuantities

    qty_row = ItemLocationQuantities.query.filter_by(user_id=user_id, item_id=item_id, location_id=location_id).first()
    if not qty_row:
        qty_row = ItemLocationQuantities(user_id=user_id, item_id=item_id, location_id=location_id, quantity=0)
        db_session.add(qty_row)
    return qty_row


def check_quantity_alerts(user_id, item_id, updated_quantities, previous_quantities):
    """Check for low/high stock alerts only if crossing thresholds."""
    from app.inventory.models import Items
    
    alerts = []
    item = Items.query.filter_by(id=item_id, user_id=user_id).first()
    
    if not item:
        return alerts

    for loc_id, new_qty in updated_quantities.items():
        old_qty = previous_quantities.get(loc_id, 0)

        # Low stock alert - only if crossing below threshold
        if item.min_quantity is not None and new_qty < item.min_quantity and old_qty >= item.min_quantity:
            alerts.append(
                {
                    "location_id": loc_id,
                    "alert_type": "low_stock",
                    "quantity": new_qty,
                    "min_quantity": item.min_quantity,
                }
            )

        # Over max alert - only if crossing above threshold
        if item.max_quantity is not None and new_qty > item.max_quantity and old_qty <= item.max_quantity:
            alerts.append(
                {
                    "location_id": loc_id,
                    "alert_type": "over_max",
                    "quantity": new_qty,
                    "max_quantity": item.max_quantity,
                }
            )
    return alerts
