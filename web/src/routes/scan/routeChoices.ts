import type { ScanStorageOptionsResponse } from "../../api/types.gen";
import {
  COUNT_CHOICE_HINT,
  COUNT_CHOICE_LABEL,
  COUNT_STORAGE_ID,
  RESTOCK_CHOICE_HINT,
  RESTOCK_CHOICE_LABEL,
  RESTOCK_STORAGE_ID,
  TAKE_CHOICE_HINT,
  TAKE_CHOICE_LABEL,
  TAKE_STORAGE_ID,
} from "../../constants";

export type ScanChoice = { id: number; label: string; hint?: string };

export type ScanRoute = { fromStorageId: number; toStorageId: number };

const RESTOCK: ScanChoice = { id: RESTOCK_STORAGE_ID, label: RESTOCK_CHOICE_LABEL, hint: RESTOCK_CHOICE_HINT };
const COUNT: ScanChoice = { id: COUNT_STORAGE_ID, label: COUNT_CHOICE_LABEL, hint: COUNT_CHOICE_HINT };
const TAKE: ScanChoice = { id: TAKE_STORAGE_ID, label: TAKE_CHOICE_LABEL, hint: TAKE_CHOICE_HINT };

const isVirtual = (storageId: number | null) => storageId !== null && storageId < 0;

/** The to-list depends on the from-pick, so both sides and their summary are built in one place. */
export function routeChoices(options: ScanStorageOptionsResponse, from: number | null) {
  const shelf = (storage: { id: number; name: string; location_name: string }): ScanChoice => ({
    id: storage.id,
    label: storage.name,
    hint: storage.location_name,
  });

  const canFill = options.to_storages.length > 0;
  const fromChoices = [
    ...(options.can_restock && canFill ? [RESTOCK] : []),
    ...(options.can_count && canFill ? [COUNT] : []),
    ...options.from_storages.map(shelf),
  ];
  const toChoices = [
    ...(isVirtual(from) ? [] : [TAKE]),
    ...options.to_storages.filter((storage) => storage.id !== from).map(shelf),
  ];
  const labelOf = (id: number) => [...fromChoices, ...toChoices].find((choice) => choice.id === id)?.label ?? "";

  return {
    from: fromChoices,
    to: toChoices,
    summary: (fromId: number, toId: number) => `${labelOf(fromId)} to ${labelOf(toId)}`,
  };
}

const soleId = (choices: ScanChoice[]) => (choices.length === 1 ? choices[0].id : null);

/** The only from-choice there is, so the screen can pick it for the scanner. */
export const soleFromId = (options: ScanStorageOptionsResponse) => soleId(routeChoices(options, null).from);

/** The only to-choice left once this from is picked. */
export const soleToId = (options: ScanStorageOptionsResponse, from: number | null) =>
  from === null ? null : soleId(routeChoices(options, from).to);

/** The from that pairs with this to: the only one that reaches it, else the current pick if it still can. */
export function fromIdForTo(options: ScanStorageOptionsResponse, to: number, current: number | null): number | null {
  const reaching = routeChoices(options, null).from.filter((from) =>
    routeChoices(options, from.id).to.some((choice) => choice.id === to),
  );
  if (reaching.length === 1) return reaching[0].id;
  return reaching.some((from) => from.id === current) ? current : null;
}

/** The one route this location can possibly make, when there is nothing to choose between. */
export function soleRoute(options: ScanStorageOptionsResponse): ScanRoute | null {
  const pairs = routeChoices(options, null).from.flatMap((from) =>
    routeChoices(options, from.id).to.map((to) => ({ fromStorageId: from.id, toStorageId: to.id })),
  );
  return pairs.length === 1 ? pairs[0] : null;
}
