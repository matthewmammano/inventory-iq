/** Every tunable number and every piece of visible copy on the guest scan screen. */

export const V2_BASENAME = "/v2";

/** Barcodes in this inventory are 12-digit UPC-A. */
export const UPC_LENGTH = 12;

/** A hardware scanner finishes a barcode in one burst; this much silence means the burst ended. */
export const SCANNER_IDLE_MS = 100;

export const MAX_VISIBLE_RESULTS = 7;

/** Fuse.js distance tolerance. Lower is stricter. */
export const SEARCH_THRESHOLD = 0.4;

export const SEARCH_KEYS = ["name", "upcs", "tags.name"] as const;

export const SCAN_SCREEN_TITLE = "Scan Inventory";
export const SCAN_SCREEN_SUBTITLE = "Point the scanner at the barcode, or type the item name";
export const SEARCH_PLACEHOLDER = "Scan item barcode or search inventory";
export const ADMIN_LINK_LABEL = "Admin";

export const LOAD_FAILED_NOTE = "Could not load the item list. Close this page and open it again.";
export const NO_ITEMS_NOTE = "No items here yet.";
export const LOADING_ITEMS_LABEL = "Loading inventory";

export const noMatchNote = (query: string) => `Nothing matches "${query}". Check the spelling or scan the barcode.`;

export const resultCountLabel = (shown: number, total: number) => `${shown} of ${total}`;
