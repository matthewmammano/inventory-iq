/** Every tunable number and every piece of visible copy on the guest scan screen. */

import type { ScanResultResponse } from "./api/types.gen";

export const V2_BASENAME = "/v2";

/** Digits this close together came from a scanner, not a person; the same gap of silence ends the burst. */
export const SCANNER_BURST_GAP_MS = 50;

/** The shortest digit run worth looking up, so a stray fast keypress is not a scan. */
export const SCANNER_MIN_DIGITS = 8;

export const MAX_VISIBLE_RESULTS = 7;

/** Fuse.js distance tolerance. Lower is stricter. */
export const SEARCH_THRESHOLD = 0.4;

export const SEARCH_KEYS = ["name", "upcs", "tags.name"] as const;

export const SCAN_SCREEN_TITLE = "Scan Inventory";
export const SCAN_SCREEN_SUBTITLE = "Point the scanner at the barcode, or type the item name";
export const SEARCH_PLACEHOLDER = "Scan item barcode or search inventory";
export const ADMIN_LINK_LABEL = "Admin";

export const LOAD_FAILED_NOTE = "Could not load the item list. Close this page and open it again.";
export const UNKNOWN_BARCODE_FAILED_NOTE = "Could not check that barcode. Try scanning it again.";
export const NO_ITEMS_NOTE = "No items here yet.";
export const LOADING_ITEMS_LABEL = "Loading inventory";

export const noMatchNote = (query: string) => `Nothing matches "${query}". Check the spelling or scan the barcode.`;

export const resultCountLabel = (shown: number, total: number) => `${shown} of ${total}`;

/** Sentinel storage ids that stand in for a real shelf. They mirror `VirtualLocation` on the server. */
export const RESTOCK_STORAGE_ID = -1;
export const COUNT_STORAGE_ID = -2;
export const TAKE_STORAGE_ID = -3;

export const LOCATION_STEP_TITLE = "Where Is This Device?";
export const LOCATION_STEP_SUBTITLE = "Pick it once. This device remembers it from now on.";
export const ROUTE_STEP_TITLE = "Where From, Where To";
export const ROUTE_STEP_SUBTITLE = "Pick where the stock leaves, then where it lands";
export const QUANTITY_STEP_TITLE = "How Many?";
export const EXPIRATION_STEP_TITLE = "Expiration Dates";

export const FROM_GROUP_LABEL = "Take from";
export const TO_GROUP_LABEL = "Put into";
export const FROM_STRIP_LABEL = "From:";
export const TO_STRIP_LABEL = "To:";

export const RESTOCK_CHOICE_LABEL = "Restock";
export const RESTOCK_CHOICE_HINT = "New stock arriving from an order";
export const COUNT_CHOICE_LABEL = "Count";
export const COUNT_CHOICE_HINT = "Correcting what is really there";
export const TAKE_CHOICE_LABEL = "Take";
export const TAKE_CHOICE_HINT = "Used up or thrown away";

export const BACK_LABEL = "Back";
export const CONTINUE_LABEL = "Continue";
export const CONTINUE_TO_DATES_LABEL = "Continue to dates";
export const SAVE_SCAN_LABEL = "Save";
/** A kiosk reads the same lists all shift, so a repeat step answers from cache. */
export const QUERY_STALE_MS = 30_000;
export const OVER_DATED_LABEL = "Save (too many selected)";
export const RESET_QUANTITY_LABEL = "Reset";
export const QUANTITY_STEP_SUBTITLE = "Tap plus or minus until the number matches what you moved";

/** The placeholder v1 serves for an item with no usable picture. */
export const NOT_FOUND_IMAGE_URL = "/static/images/not-found.jpg";

export const PICK_LOCATION_PROMPT = "Pick a location";
export const PICK_FROM_PROMPT = "Pick where the stock comes from";
export const PICK_TO_PROMPT = "Pick where the stock goes";
export const LOADING_LOCATIONS_LABEL = "Loading locations";
export const LOADING_STORAGES_LABEL = "Loading storage";
export const LOADING_ITEM_LABEL = "Loading item";
export const LOADING_DATES_LABEL = "Loading dates";
export const NO_LOCATIONS_NOTE = "No locations set up yet. An admin adds these.";
export const NO_FROM_NOTE = "Nothing here to take from.";
export const NO_TO_NOTE = "Nowhere here to put stock.";
export const SAVE_FAILED_NOTE = "Could not save that scan. Try again.";

export const STALE_COUNT_NOTE = "This location is due for a count.";
export const NEW_DATE_LABEL = "Another date";
export const OTHER_DATE_LABEL = "No date on the package";
export const ADD_DATE_LABEL = "Add a date";

export const MINUS_LABEL = "-";
export const PLUS_LABEL = "+";

/** The steps the plus and minus buttons offer when an item allows quick adjusting. */
export const QUICK_ADJUST_STEPS = [1, 5, 10] as const;
export const SINGLE_STEP = [1] as const;

export const suggestedRestockNote = (amount: number) => `Suggested restock is ${amount}.`;
export const datedProgressLabel = (dated: number, target: number) => `${dated} of ${target} dated`;
export const trackedHereLabel = (quantity: number) => `${quantity} tracked here`;
export const initialCountNote = (itemName: string) => `${itemName} still needs its first full count.`;

/** How long the confirmation bar stays up before it leaves on its own. */
export const TOAST_VISIBLE_MS = 7000;

export const TOAST_ICONS = { success: "OK", warning: "!", error: "X" } as const;

/** What the saved scan actually did, phrased the way the operation reads out loud. */
export function scanSavedNote(result: ScanResultResponse): string {
  const from = result.from_storage?.name ?? "";
  const to = result.to_storage?.name ?? "";
  switch (result.operation) {
    case "COUNT":
      return `Set ${result.item_name} quantity to ${result.quantity} at ${to}.`;
    case "RESTOCK":
      return `Restocked ${result.quantity} ${result.item_name} to ${to}.`;
    case "TAKEOUT":
      return `Removed ${result.quantity} ${result.item_name} from ${from}.`;
    case "TRANSFER":
      return `Transferred ${result.quantity} ${result.item_name} from ${from} to ${to}.`;
  }
}
