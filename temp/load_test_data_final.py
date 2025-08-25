"""
Load test data from log.sql using verified UPC mapping.
Only loads data for the 72 items with near-identical matches (85%+ similarity).
"""

import logging
import re
from datetime import datetime

from app import create_app, db
from app.auth.models import UserItemLocations, Users
from app.inventory.models import ActionLogs, Items, OperationType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Verified UPC mapping - only items with 85%+ similarity
OLD_UPC_TO_NEW_UPC = {
    "000000000000": "500000000937",  # Sterile Water (250mL)
    "000000000017": "500000000272",  # Combine Pad - 5x9
    "000000000024": "500000000449",  # Gauze Pad - 4x4
    "000000000031": "500000000616",  # Multi-Trauma Dressing - 12x30
    "000000000086": "500000000074",  # Band-Aids
    "000000000116": "500000000494",  # Glucometer Test Strips
    "000000000147": "500000000845",  # Pink Oral Airway - 40mm
    "000000000154": "500000000128",  # Blue Oral Airway - 50mm
    "000000000161": "500000000111",  # Black Oral Airway - 60mm
    "000000000178": "500000001057",  # White Oral Airway - 70mm
    "000000000185": "500000000517",  # Green Oral Airway - 80mm
    "000000000192": "500000001071",  # Yellow Oral Airway - 90mm
    "000000000208": "500000000883",  # Red Oral Airway - 100mm
    "000000000215": "500000000814",  # Orange Oral Airway - 110mm
    "000000000239": "500000000647",  # Nasal Airway - 20Fr
    "000000000246": "500000000654",  # Nasal Airway - 22Fr
    "000000000253": "500000000661",  # Nasal Airway - 24Fr
    "000000000260": "500000000678",  # Nasal Airway - 26Fr
    "000000000277": "500000000685",  # Nasal Airway - 28Fr
    "000000000284": "500000000692",  # Nasal Airway - 30Fr
    "000000000291": "500000000708",  # Nasal Airway - 32Fr
    "000000000307": "500000000715",  # Nasal Airway - 34Fr
    "000000000314": "500000000722",  # Nasal Airway - 36Fr
    "000000000338": "500000000753",  # NRB - Adult
    "000000000345": "500000000760",  # NRB - Child
    "000000000369": "500000000739",  # NC - Adult
    "000000000376": "500000000746",  # NC - Child
    "000000000383": "500000000197",  # BVM - Adult
    "000000000390": "500000000203",  # BVM - Child
    "000000000406": "500000000210",  # BVM - Infant
    "000000000420": "500000000821",  # PEEP Valve
    "000000000468": "500000000425",  # French Catheter - 6Fr
    "000000000475": "500000000432",  # French Catheter - 8Fr
    "000000000482": "500000000371",  # French Catheter - 10Fr
    "000000000499": "500000000388",  # French Catheter - 12Fr
    "000000000505": "500000000395",  # French Catheter - 14Fr
    "000000000512": "500000000401",  # French Catheter - 16Fr
    "000000000529": "500000000418",  # French Catheter - 18Fr
    "000000000543": "500000000470",  # Gloves - Small
    "000000000550": "500000000463",  # Gloves - Medium
    "000000000567": "500000000456",  # Gloves - Large
    "000000000574": "500000000487",  # Gloves - X-Large
    "000000000581": "500000000975",  # Surgical Mask
    "000000000598": "500000000623",  # N95 Mask
    "000000000604": "500000000357",  # Eye Protection
    "000000000642": "500000000920",  # Shoe Covers
    "000000000666": "500000001033",  # Tyvek Suit - Large
    "000000000673": "500000001040",  # Tyvek Suit - X-Large
    "000000000680": "500000001026",  # Tyvek Suit - 2X-Large
    "000000000697": "500000000104",  # Biohazard Bags
    "000000000703": "500000000050",  # Amber - Bleach Wipes
    "000000000710": "500000000869",  # Purple - Alcohol Wipes
    "000000000741": "500000000227",  # C-Collar - Adult
    "000000000758": "500000000234",  # C-Collar - Child
    "000000000765": "500000000524",  # Head Blocks - Adult
    "000000000772": "500000000531",  # Head Blocks - Child
    "000000000857": "500000000159",  # BP Cuff - Large Adult
    "000000000864": "500000000135",  # BP Cuff - Adult
    "000000000888": "500000000142",  # BP Cuff - Child
    "000000000901": "500000000944",  # Stethoscope
    "000000000918": "500000000852",  # Pulse Oximeter
    "000000000925": "500000000067",  # Aspirin
    "000000000932": "500000000333",  # Epi Pen - Adult
    "000000000949": "500000000340",  # Epi Pen - Child
    "000000000956": "500000000630",  # Narcan
    "000000000970": "500000000012",  # AED Pad - Adult
    "000000000987": "500000000029",  # AED Pad - Child
    "000000000994": "500000000005",  # AED Battery
    "000000001090": "500000000098",  # Basin
    "000000001106": "500000001019",  # Triage Tags
    "000000001168": "500000000777",  # OB Kit
    "000000001175": "500000000173",  # Bulb Syringe
}


def parse_sql_file(filepath: str) -> list:
    """Parse log.sql file and extract INSERT statements."""
    logger.info(f"Parsing SQL file: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Extract all INSERT statements with VALUES
    pattern = r"INSERT INTO `log`.*?VALUES\s*\n(.*?)(?=INSERT INTO|$)"
    matches = re.findall(pattern, content, re.DOTALL)

    all_rows = []
    for match in matches:
        # Parse individual value rows
        row_pattern = r"\((\d+),\s*'([^']+)',\s*'([^']+)',\s*'([^']+)',\s*(\d+)\)"
        rows = re.findall(row_pattern, match)
        all_rows.extend(rows)

    logger.info(f"Extracted {len(all_rows)} data rows from SQL file")
    return all_rows


def map_transfer_type_to_operation(transfer_type: str, location_name: str) -> tuple:
    """Map legacy transfer types to new operation types."""
    transfer_type = transfer_type.strip().upper()

    if "RECOUNT" in transfer_type:
        return OperationType.count, None, location_name
    elif "RESTOCK" in transfer_type:
        return OperationType.restock, None, location_name
    elif "TAKEOUT" in transfer_type or "TAKE" in transfer_type:
        return OperationType.takeout, location_name, None
    elif "TRANSFER" in transfer_type:
        return OperationType.transfer, "Shelf", location_name
    else:
        return OperationType.count, None, location_name


def parse_datetime(date_str: str) -> datetime:
    """Parse datetime from log format."""
    try:
        return datetime.strptime(date_str, "%m/%d/%Y %H:%M:%S")
    except ValueError:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            logger.error(f"Unable to parse datetime: {date_str}")
            return datetime.now()


def get_or_create_location(location_name: str, user_id: int) -> int:
    """Get or create location for user."""
    if not location_name:
        return None

    location = UserItemLocations.query.filter_by(name=location_name, user_id=user_id).first()
    if not location:
        location = UserItemLocations(name=location_name, user_id=user_id, user_access_from=True, user_access_to=True)
        db.session.add(location)
        db.session.flush()
        logger.info(f"Created new location: {location_name}")

    return location.id


def get_item_id_by_upc(upc: str, user_id: int) -> int:
    """Get item ID by UPC."""
    item = Items.query.filter_by(upc=upc, user_id=user_id).first()
    if item:
        return item.id
    else:
        logger.error(f"Item not found with UPC: {upc}")
        return None


def load_test_data():
    """Main function to load test data with verified mapping."""
    app = create_app()

    with app.app_context():
        logger.info("Starting final test data loading...")

        # Get the user
        user = Users.query.first()
        if not user:
            logger.error("No users found!")
            return

        logger.info(f"Using user: {user.display_name} (ID: {user.id})")

        # Clear existing ActionLogs
        logger.info("Clearing existing ActionLogs...")
        ActionLogs.query.delete()
        db.session.commit()
        logger.info("ActionLogs table cleared")

        # Build new UPC to item ID mapping
        logger.info("Building UPC to item ID mapping...")
        upc_to_item_id = {}
        missing_items = []

        for old_upc, new_upc in OLD_UPC_TO_NEW_UPC.items():
            item_id = get_item_id_by_upc(new_upc, user.id)
            if item_id:
                upc_to_item_id[old_upc] = item_id
            else:
                missing_items.append((old_upc, new_upc))

        logger.info(f"Successfully mapped {len(upc_to_item_id)} UPC codes to item IDs")
        if missing_items:
            logger.warning(f"Missing {len(missing_items)} items in database:")
            for old_upc, new_upc in missing_items:
                logger.warning(f"  {old_upc} -> {new_upc}")

        # Parse SQL file
        sql_rows = parse_sql_file("log.sql")

        # Take first 80% of rows for training
        rows_to_process = int(len(sql_rows) * 0.8)
        test_rows = sql_rows[:rows_to_process]

        logger.info(f"Processing first {rows_to_process} rows (training data)")
        logger.info(f"Reserved {len(sql_rows) - rows_to_process} rows for testing")

        success_count = 0
        skip_count = 0
        error_count = 0

        for row in test_rows:
            try:
                id_val, date_str, upc, transfer_type, number = row

                # Clean UPC (remove leading zeros, pad to 12)
                upc_clean = upc.strip().lstrip("0").zfill(12)

                # Skip if we don't have a mapping for this UPC
                if upc_clean not in upc_to_item_id:
                    skip_count += 1
                    continue

                item_id = upc_to_item_id[upc_clean]

                # Parse operation details
                operation_type, from_loc_name, to_loc_name = map_transfer_type_to_operation(
                    transfer_type, transfer_type.split(" - ")[-1] if " - " in transfer_type else "Shelf"
                )

                # Get or create locations
                from_location_id = get_or_create_location(from_loc_name, user.id) if from_loc_name else None
                to_location_id = get_or_create_location(to_loc_name, user.id) if to_loc_name else None

                # Parse datetime
                time_scanned = parse_datetime(date_str)

                # Create ActionLog entry
                action_log = ActionLogs(
                    user_id=user.id,
                    item_id=item_id,
                    operation_type=operation_type,
                    from_location_id=from_location_id,
                    to_location_id=to_location_id,
                    quantity_delta=int(number),
                    admin_action=True,  # Mark as admin action for ML training
                    time_scanned=time_scanned,
                )

                db.session.add(action_log)
                success_count += 1

                # Commit in batches
                if success_count % 100 == 0:
                    db.session.commit()
                    logger.info(f"Processed {success_count} records...")

            except Exception as e:
                error_count += 1
                logger.error(f"Error processing row {row}: {e}")
                continue

        # Final commit
        db.session.commit()

        logger.info("Test data loading complete!")
        logger.info(f"Successfully loaded: {success_count} records")
        logger.info(f"Skipped (no mapping): {skip_count} records")
        logger.info(f"Errors: {error_count} records")
        logger.info("Training data loaded from first 80% of log.sql")
        logger.info(f"Remaining 20% ({len(sql_rows) - rows_to_process} rows) reserved for testing predictions")

        # Show sample data
        sample_logs = ActionLogs.query.order_by(ActionLogs.time_scanned.asc()).limit(5).all()
        logger.info("\nSample loaded data:")
        for log in sample_logs:
            item = Items.query.get(log.item_id)
            logger.info(f"  {log.time_scanned} - {log.operation_type.value} - {item.name} - Qty: {log.quantity_delta}")


if __name__ == "__main__":
    load_test_data()
