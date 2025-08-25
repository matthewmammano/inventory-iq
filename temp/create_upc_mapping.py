"""
Create UPC mapping from log.sql old codes to real database items.
Only maps if item names are NEARLY IDENTICAL (strict fuzzy matching).
"""

import logging
from difflib import SequenceMatcher

from app import create_app
from app.auth.models import Users
from app.inventory.models import Items

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mapping from log.sql UPC codes to legacy item names
OLD_UPC_TO_NAME = {
    "000000000000": "Sterile Water (250mL)",
    "000000000017": "Combine Pad - 5x9",
    "000000000024": "Gauze Pad - 4x4",
    "000000000031": "Multi-Trauma Dressing - 12x30",
    "000000000048": "Chest Seal",
    "000000000055": 'Roller Gauze - 2"',
    "000000000062": 'Roller Gauze - 4"',
    "000000000079": "Tourniquet",
    "000000000086": "Band-Aids",
    "000000000093": 'Clear Tape - 1"',
    "000000000109": "Lancet",
    "000000000116": "Glucometer Test Strips",
    "000000000123": 'Cloth Tape - 2" (UNUSED)',
    "000000000130": 'Cloth Tape - 3" (UNUSED)',
    "000000000147": "Pink Oral Airway - 40mm",
    "000000000154": "Blue Oral Airway - 50mm",
    "000000000161": "Black Oral Airway - 60mm",
    "000000000178": "White Oral Airway - 70mm",
    "000000000185": "Green Oral Airway - 80mm",
    "000000000192": "Yellow Oral Airway - 90mm",
    "000000000208": "Red Oral Airway - 100mm",
    "000000000215": "Orange Oral Airway - 110mm",
    "000000000222": "Complete Kit",
    "000000000239": "Nasal Airway - 20Fr",
    "000000000246": "Nasal Airway - 22Fr",
    "000000000253": "Nasal Airway - 24Fr",
    "000000000260": "Nasal Airway - 26Fr",
    "000000000277": "Nasal Airway - 28Fr",
    "000000000284": "Nasal Airway - 30Fr",
    "000000000291": "Nasal Airway - 32Fr",
    "000000000307": "Nasal Airway - 34Fr",
    "000000000314": "Nasal Airway - 36Fr",
    "000000000321": "Surgi-Lube",
    "000000000338": "NRB - Adult",
    "000000000345": "NRB - Child",
    "000000000352": "NRB - Infant",
    "000000000369": "NC - Adult",
    "000000000376": "NC - Child",
    "000000000383": "BVM - Adult",
    "000000000390": "BVM - Child",
    "000000000406": "BVM - Infant",
    "000000000413": "HEPA Filter",
    "000000000420": "PEEP Valve",
    "000000000437": "CPAP",
    "000000000444": "CPAP Filter",
    "000000000451": "Yankauer Set",
    "000000000468": "French Catheter - 6Fr",
    "000000000475": "French Catheter - 8Fr",
    "000000000482": "French Catheter - 10Fr",
    "000000000499": "French Catheter - 12Fr",
    "000000000505": "French Catheter - 14Fr",
    "000000000512": "French Catheter - 16Fr",
    "000000000529": "French Catheter - 18Fr",
    "000000000536": "Suction Container and Lid",
    "000000000543": "Gloves - Small",
    "000000000550": "Gloves - Medium",
    "000000000567": "Gloves - Large",
    "000000000574": "Gloves - X-Large",
    "000000000581": "Surgical Mask",
    "000000000598": "N95 Mask",
    "000000000604": "Eye Protection",
    "000000000611": "Respirator Filters",
    "000000000628": "Gown/Apron",
    "000000000635": "Faceshield",
    "000000000642": "Shoe Covers",
    "000000000666": "Tyvek Suit - Large",
    "000000000673": "Tyvek Suit - X-Large",
    "000000000680": "Tyvek Suit - 2X-Large",
    "000000000697": "Biohazard Bags",
    "000000000703": "Amber - Bleach Wipes",
    "000000000710": "Purple - Alcohol Wipes",
    "000000000727": "Red - Germicide Wipes",
    "000000000734": "Grey - Combo Wipes",
    "000000000741": "C-Collar - Adult",
    "000000000758": "C-Collar - Child",
    "000000000765": "Head Blocks - Adult",
    "000000000772": "Head Blocks - Child",
    "000000000789": "SAM Splint",
    "000000000796": 'Board Splints - 12"',
    "000000000802": 'Board Splints - 18"',
    "000000000819": "Board Splints - 3x15",
    "000000000826": "Board Splints - 3x36",
    "000000000833": "Board Splints - 3x54",
    "000000000840": "Cravat",
    "000000000857": "BP Cuff - Large Adult",
    "000000000864": "BP Cuff - Adult",
    "000000000871": "BP Cuff - Automatic",
    "000000000888": "BP Cuff - Child",
    "000000000895": "BP Cuff - Infant",
    "000000000901": "Stethoscope",
    "000000000918": "Pulse Oximeter",
    "000000000925": "Aspirin",
    "000000000932": "Epi Pen - Adult",
    "000000000949": "Epi Pen - Child",
    "000000000956": "Narcan",
    "000000000963": "Glucose",
    "000000000970": "AED Pad - Adult",
    "000000000987": "AED Pad - Child",
    "000000000994": "AED Battery",
    "000000001007": "ZOLL LifeBand",
    "000000001014": "Trauma Shear",
    "000000001021": "Seat Belt Cutter",
    "000000001038": "Ring Cutter",
    "000000001045": "Pen Light",
    "000000001052": "Emergency Blanket",
    "000000001069": "Tongue Depressor",
    "000000001083": "Vomit Bag",
    "000000001090": "Basin",
    "000000001106": "Triage Tags",
    "000000001113": "Alcohol Pad",
    "000000001120": "Ice Pack",
    "000000001137": "Heat Pack",
    "000000001144": "Chux Pad",
    "000000001151": "Mega Mover",
    "000000001168": "OB Kit",
    "000000001175": "Bulb Syringe",
}


def normalize_name(name: str) -> str:
    """Normalize item name for comparison."""
    if not name:
        return ""

    # Convert to lowercase and clean up
    normalized = name.lower().strip()

    # Replace common variations
    replacements = {
        '"': "inch",
        "'": "ft",
        "-": " ",
        "_": " ",
        "faceshield": "face shield",
        "n95 mask": "n95",
        "surgical mask": "face mask",
        "alcohol pad": "alcohol pads",
        "band-aids": "band aid",
        "band-aid": "band aid",
    }

    for old, new in replacements.items():
        normalized = normalized.replace(old, new)

    # Remove extra spaces
    normalized = " ".join(normalized.split())

    return normalized


def similarity_score(name1: str, name2: str) -> float:
    """Calculate similarity score between two names (0-1)."""
    norm1 = normalize_name(name1)
    norm2 = normalize_name(name2)

    # Use SequenceMatcher for character-level similarity
    char_similarity = SequenceMatcher(None, norm1, norm2).ratio()

    # Also check word-level similarity
    words1 = set(norm1.split())
    words2 = set(norm2.split())

    if len(words1) == 0 and len(words2) == 0:
        return 1.0
    if len(words1) == 0 or len(words2) == 0:
        return 0.0

    word_similarity = len(words1 & words2) / len(words1 | words2)

    # Combine scores (character similarity is more important)
    combined_score = (char_similarity * 0.7) + (word_similarity * 0.3)

    return combined_score


def find_best_match(target_name: str, real_items: list, min_similarity: float = 0.85) -> tuple:
    """
    Find best matching real item for target name.

    Args:
        target_name: Name to match
        real_items: List of real items to search
        min_similarity: Minimum similarity score (0.85 = 85% match required)

    Returns:
        tuple: (best_item, similarity_score) or (None, 0)
    """
    best_item = None
    best_score = 0.0

    for item in real_items:
        if not item.name:
            continue

        score = similarity_score(target_name, item.name)

        if score > best_score and score >= min_similarity:
            best_score = score
            best_item = item

    return best_item, best_score


def create_mapping():
    """Create mapping from old UPC codes to new UPC codes."""
    app = create_app()

    with app.app_context():
        logger.info("Creating UPC mapping with strict fuzzy matching...")

        # Get the user
        user = Users.query.first()
        if not user:
            logger.error("No users found!")
            return

        logger.info(f"Using user: {user.display_name} (ID: {user.id})")

        # Get all real items (with UPC starting with 5)
        real_items = Items.query.filter(Items.user_id == user.id, Items.upc.like("5%"), Items.active == True).all()

        logger.info(f"Found {len(real_items)} real items to match against")

        # Create mapping
        mapping = {}
        matched_count = 0
        unmatched_count = 0

        logger.info("\n=== MATCHING RESULTS ===")
        logger.info("Old UPC -> Old Name -> New Name (New UPC) [Similarity%]")
        logger.info("-" * 80)

        for old_upc, old_name in OLD_UPC_TO_NAME.items():
            best_item, score = find_best_match(old_name, real_items, min_similarity=0.85)

            if best_item:
                mapping[old_upc] = best_item.upc
                matched_count += 1
                logger.info(f"{old_upc} -> '{old_name}' -> '{best_item.name}' ({best_item.upc}) [{score:.1%}]")
            else:
                unmatched_count += 1
                # Find best match even if below threshold for debugging
                best_item_any, score_any = find_best_match(old_name, real_items, min_similarity=0.0)
                if best_item_any:
                    logger.warning(
                        f"{old_upc} -> '{old_name}' -> NO MATCH (best: '{best_item_any.name}' [{score_any:.1%}] - too low)"
                    )
                else:
                    logger.warning(f"{old_upc} -> '{old_name}' -> NO MATCH FOUND")

        logger.info("-" * 80)
        logger.info(f"SUMMARY: {matched_count} matched, {unmatched_count} unmatched")

        # Output mapping as Python dict
        logger.info("\n=== PYTHON MAPPING ===")
        logger.info("OLD_UPC_TO_NEW_UPC = {")
        for old_upc, new_upc in sorted(mapping.items()):
            old_name = OLD_UPC_TO_NAME[old_upc]
            logger.info(f'    "{old_upc}": "{new_upc}",  # {old_name}')
        logger.info("}")

        return mapping


if __name__ == "__main__":
    create_mapping()
