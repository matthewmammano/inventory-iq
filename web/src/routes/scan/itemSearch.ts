import Fuse from "fuse.js";

import type { ItemListResponseItemResponse as Item } from "../../api/types.gen";
import { MAX_VISIBLE_RESULTS, SEARCH_KEYS, SEARCH_THRESHOLD } from "../../constants";

const lastAccessedFirst = (left: Item, right: Item) => right.last_accessed.localeCompare(left.last_accessed);

export const findByBarcode = (items: Item[], upc: string) => items.find((item) => item.upcs.includes(upc));

/** Matches a typed query the way v1 did: fuzzy over name, barcodes and tag names, best score first. */
export function searchItems(items: Item[], query: string): Item[] {
  if (!query.trim()) return items.slice(0, MAX_VISIBLE_RESULTS);

  const fuse = new Fuse(items, {
    keys: [...SEARCH_KEYS],
    threshold: SEARCH_THRESHOLD,
    includeScore: true,
    ignoreLocation: true,
  });

  return fuse
    .search(query)
    .sort((left, right) => (left.score ?? 0) - (right.score ?? 0) || lastAccessedFirst(left.item, right.item))
    .slice(0, MAX_VISIBLE_RESULTS)
    .map((result) => result.item);
}
