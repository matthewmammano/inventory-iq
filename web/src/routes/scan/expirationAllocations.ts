import type { ExpirationEntryResponse } from "../../api/types.gen";

export type DateEntry = { expiresOn: string | null; quantity: number };

const sum = (rows: DateEntry[]) => rows.reduce((running, row) => running + row.quantity, 0);

export const datedTotal = (known: DateEntry[], added: DateEntry[], other: number) =>
  sum(known) + sum(added) + other;

/** A takeout may come up short of its target; everything else has to account for every unit. */
export function isComplete(entry: ExpirationEntryResponse, total: number, added: DateEntry[]): boolean {
  if (added.some((row) => row.quantity > 0 && !row.expiresOn)) return false;
  if (entry.requires_exact_total) return total === entry.target_quantity;
  return total > 0 && total <= entry.target_quantity;
}

export function allocationsOf(known: DateEntry[], added: DateEntry[], other: number) {
  const dated = [...known, ...added]
    .filter((row) => row.quantity > 0 && row.expiresOn)
    .map((row) => ({ expires_on: row.expiresOn, quantity: row.quantity }));
  return other > 0 ? [...dated, { expires_on: null, quantity: other }] : dated;
}
