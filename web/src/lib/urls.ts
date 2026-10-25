/** The v1 server-rendered routes this screen hands off to until Phase 4 replaces them. */

const guestRoot = (agencyId: number) => `/inventory/${agencyId}`;

export const adminLoginUrl = (agencyId: number) => `${guestRoot(agencyId)}/admin`;

export const scanItemUrl = (agencyId: number, itemId: number) => `${guestRoot(agencyId)}/scan?item_id=${itemId}`;

/** v1 records the unrecognized barcode server side, so an unmatched scan goes back through it. */
export const unknownBarcodeUrl = (agencyId: number, upc: string) =>
  `${guestRoot(agencyId)}/?scan_error=not_found&unknown_upc=${encodeURIComponent(upc)}`;
