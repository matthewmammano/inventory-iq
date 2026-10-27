/** Every tunable number and every piece of visible copy on the v2 screens. */

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
export const EXPIRATION_COLUMN_LABEL = "Expiration date";
export const AVAILABLE_COLUMN_LABEL = "Available";
export const SELECTED_COLUMN_LABEL = "Selected";

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
export const initialCountNote = (itemName: string) => `${itemName} still needs its first full count.`;

/** A photo that arrives inside this grace period replaces the empty box directly, so no backup is seen. */
export const ITEM_PHOTO_BACKUP_DELAY_MS = 250;

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

/** Whole screens the router owns. A flow's steps stay internal state, so none of them appear here. */
export const SCAN_PATH = "/";
export const SIGN_IN_PATH = "/sign-in";
export const ADMIN_PATH = "/admin";

/** The one status a screen branches on; every other refusal just shows the message the API sent. */
export const HTTP_CONFLICT = 409;

export const SIGN_IN_TITLE = "Sign In";
export const SIGN_IN_SUBTITLE = "Enter the email and password for your squad account";
export const EMAIL_LABEL = "Email";
export const PASSWORD_LABEL = "Password";
export const SIGN_IN_LABEL = "Sign in";
export const SIGN_IN_PENDING_LABEL = "Signing in";
export const SIGN_IN_UNREACHABLE_NOTE = "Could not reach the server. Try again.";
export const SET_PASSWORD_LABEL = "Set a password";
export const CONTINUE_TO_SCAN_LABEL = "Go to scanning";
export const SIGN_OUT_LABEL = "Sign out";
export const LOADING_ACCOUNT_LABEL = "Loading account";
export const signedInAsNote = (name: string) => `This device is signed in as ${name}.`;

export const ADMIN_PIN_TITLE = "Admin PIN";
export const ADMIN_PIN_SUBTITLE = "Tap the 4-digit PIN to unlock the admin screens";
export const ADMIN_PIN_LENGTH = 4;
export const UNLOCK_LABEL = "Unlock admin";
export const UNLOCK_PENDING_LABEL = "Checking PIN";
export const UNLOCK_UNREACHABLE_NOTE = "Could not check that PIN. Try again.";
export const TEMPORARY_PIN_LABEL = "Email me a temporary PIN";
export const TEMPORARY_PIN_SENT_NOTE = "Temporary PIN sent to the account email.";
export const TEMPORARY_PIN_CONFIRM_TITLE = "Email a temporary PIN?";
export const TEMPORARY_PIN_CONFIRM_NOTE = "We will send a one-time PIN to the account email. The current PIN keeps working.";
export const TEMPORARY_PIN_CONFIRM_LABEL = "Send it";
export const TEMPORARY_PIN_FAILED_NOTE = "Could not send a temporary PIN. Try again.";
export const ADMIN_UNLOCKED_TITLE = "Admin Unlocked";
export const ADMIN_UNLOCKED_NOTE = "Admin is unlocked on this device.";
export const OPEN_ADMIN_LABEL = "Open admin";
export const LOCK_ADMIN_LABEL = "Lock admin now";
export const LOADING_ADMIN_LABEL = "Checking admin";

export const KEYPAD_DIGITS = ["1", "2", "3", "4", "5", "6", "7", "8", "9"] as const;
export const KEYPAD_ZERO = "0";
export const KEYPAD_CLEAR_LABEL = "Clear";
export const KEYPAD_DELETE_LABEL = "Delete";
export const pinProgressLabel = (entered: number, length: number) => `${entered} of ${length} digits entered`;

export const SCAN_STATUS_READY = "Ready to scan";
export const SCAN_STATUS_LOADING = "Loading inventory";
export const SCAN_STATUS_OFFLINE = "No internet connection";
export const SCAN_STATUS_FAILED = "Cannot reach the item list";

export const QUICK_ACCESS_LABEL = "Quick Access";
export const SEARCH_RESULTS_LABEL = "Search Results";
export const VIEW_ALL_LABEL = "View All";
export const ALL_ITEMS_TITLE = "All Items";
export const ALL_ITEMS_SUBTITLE = "Every item in name order. Tap one to pick it.";
export const CLOSE_LABEL = "Close";
export const CANCEL_LABEL = "Cancel";
