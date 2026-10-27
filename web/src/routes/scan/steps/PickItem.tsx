import { Loading } from "@usefragments/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import {
  getApiV1AgenciesByAgencyIdItemsOptions,
  postApiV1AgenciesByAgencyIdUnknownBarcodesMutation,
} from "../../../api/@tanstack/react-query.gen";
import { ItemRow } from "../../../components/ItemRow";
import { Modal } from "../../../components/Modal";
import { Note } from "../../../components/Note";
import { Panel } from "../../../components/Panel";
import { ScanField } from "../../../components/ScanField";
import { ScanStatus } from "../../../components/ScanStatus";
import { SectionHeading } from "../../../components/SectionHeading";
import type { ToastMessage } from "../../../components/Toast";
import {
  ALL_ITEMS_SUBTITLE,
  ALL_ITEMS_TITLE,
  LOADING_ITEMS_LABEL,
  LOAD_FAILED_NOTE,
  NO_ITEMS_NOTE,
  QUICK_ACCESS_LABEL,
  SEARCH_RESULTS_LABEL,
  UNKNOWN_BARCODE_FAILED_NOTE,
  VIEW_ALL_LABEL,
  noMatchNote,
  resultCountLabel,
} from "../../../constants";
import { useBarcodeScanner } from "../../../hooks/useBarcodeScanner";
import { useScanStatus } from "../../../hooks/useScanStatus";
import { findByBarcode, searchItems, sortByName } from "../itemSearch";

import "./PickItem.css";

export type PickedItem = { id: number; name: string; imageUrl: string };

type PickItemProps = {
  agencyId: number;
  onPick: (item: PickedItem) => void;
  onNotice: (message: ToastMessage) => void;
};

/** The first step: find one item, by gun or by typing. */
export function PickItem({ agencyId, onPick, onNotice }: PickItemProps) {
  const [query, setQuery] = useState("");
  const [browsingAll, setBrowsingAll] = useState(false);
  const items = useQuery(getApiV1AgenciesByAgencyIdItemsOptions({ path: { agency_id: agencyId } }));
  const status = useScanStatus({ failed: items.isError, loading: items.isPending });

  const allItems = useMemo(() => items.data ?? [], [items.data]);
  const results = useMemo(() => searchItems(allItems, query), [allItems, query]);
  const alphabetical = useMemo(() => sortByName(allItems), [allItems]);
  const listed = !items.isError && !items.isPending && allItems.length > 0;

  const reportUnknown = useMutation({
    ...postApiV1AgenciesByAgencyIdUnknownBarcodesMutation(),
    onSuccess: (result) => onNotice({ tone: "warning", text: result.message }),
    onError: () => onNotice({ tone: "error", text: UNKNOWN_BARCODE_FAILED_NOTE }),
  });

  const scanBarcode = (upc: string) => {
    setQuery("");
    const matched = findByBarcode(allItems, upc);
    if (matched) {
      onPick({ id: matched.id, name: matched.name, imageUrl: matched.image_url });
      return;
    }
    reportUnknown.mutate({ path: { agency_id: agencyId }, query: { upc } });
  };

  useBarcodeScanner(scanBarcode);

  const pickAndClose = (item: PickedItem) => {
    setBrowsingAll(false);
    onPick(item);
  };

  return (
    <div className="iq-search iq-fit">
      <Panel>
        <ScanStatus state={status} />
        <ScanField
          value={query}
          onValueChange={setQuery}
          count={results.length > 0 ? resultCountLabel(results.length, allItems.length) : undefined}
        />
        {listed ? (
          <SectionHeading
            label={query.trim() ? SEARCH_RESULTS_LABEL : QUICK_ACCESS_LABEL}
            actionLabel={VIEW_ALL_LABEL}
            onAction={() => setBrowsingAll(true)}
          />
        ) : null}
        <Results
          failed={items.isError}
          loading={items.isPending}
          query={query}
          results={results}
          total={allItems.length}
          onPick={onPick}
        />
      </Panel>
      <Modal
        open={browsingAll}
        onClose={() => setBrowsingAll(false)}
        title={ALL_ITEMS_TITLE}
        description={ALL_ITEMS_SUBTITLE}
      >
        <ItemList items={alphabetical} onPick={pickAndClose} />
      </Modal>
    </div>
  );
}

type ItemListProps = {
  items: ReturnType<typeof searchItems>;
  scrolling?: boolean;
  onPick: (item: PickedItem) => void;
};

function ItemList({ items, scrolling, onPick }: ItemListProps) {
  return (
    <ul className={scrolling ? "iq-results iq-scroll" : "iq-results"}>
      {items.map((item) => (
        <ItemRow
          key={item.id}
          item={item}
          onPick={(picked) => onPick({ id: picked.id, name: picked.name, imageUrl: picked.image_url })}
        />
      ))}
    </ul>
  );
}

type ResultsProps = {
  failed: boolean;
  loading: boolean;
  query: string;
  results: ReturnType<typeof searchItems>;
  total: number;
  onPick: (item: PickedItem) => void;
};

function Results({ failed, loading, query, results, total, onPick }: ResultsProps) {
  if (failed) return <Note>{LOAD_FAILED_NOTE}</Note>;
  if (loading) return <Loading label={LOADING_ITEMS_LABEL} />;
  if (total === 0) return <Note>{NO_ITEMS_NOTE}</Note>;
  if (results.length === 0) return <Note>{noMatchNote(query)}</Note>;

  return <ItemList items={results} scrolling onPick={onPick} />;
}
