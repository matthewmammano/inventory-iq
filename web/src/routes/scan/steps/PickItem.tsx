import { Loading } from "@usefragments/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import {
  getApiV1AgenciesByAgencyIdItemsOptions,
  postApiV1AgenciesByAgencyIdUnknownBarcodesMutation,
} from "../../../api/@tanstack/react-query.gen";
import { ItemRow } from "../../../components/ItemRow";
import { Note } from "../../../components/Note";
import { Panel } from "../../../components/Panel";
import { ScanField } from "../../../components/ScanField";
import type { ToastMessage } from "../../../components/Toast";
import {
  LOADING_ITEMS_LABEL,
  LOAD_FAILED_NOTE,
  NO_ITEMS_NOTE,
  noMatchNote,
  resultCountLabel,
  UNKNOWN_BARCODE_FAILED_NOTE,
} from "../../../constants";
import { useBarcodeScanner } from "../../../hooks/useBarcodeScanner";
import { findByBarcode, searchItems } from "../itemSearch";

import "./PickItem.css";

export type PickedItem = { id: number; name: string };

type PickItemProps = {
  agencyId: number;
  onPick: (item: PickedItem) => void;
  onNotice: (message: ToastMessage) => void;
};

/** The first step: find one item, by gun or by typing. */
export function PickItem({ agencyId, onPick, onNotice }: PickItemProps) {
  const [query, setQuery] = useState("");
  const items = useQuery(getApiV1AgenciesByAgencyIdItemsOptions({ path: { agency_id: agencyId } }));

  const allItems = useMemo(() => items.data ?? [], [items.data]);
  const results = useMemo(() => searchItems(allItems, query), [allItems, query]);

  const reportUnknown = useMutation({
    ...postApiV1AgenciesByAgencyIdUnknownBarcodesMutation(),
    onSuccess: (result) => onNotice({ tone: "warning", text: result.message }),
    onError: () => onNotice({ tone: "error", text: UNKNOWN_BARCODE_FAILED_NOTE }),
  });

  const scanBarcode = (upc: string) => {
    setQuery("");
    const matched = findByBarcode(allItems, upc);
    if (matched) {
      onPick({ id: matched.id, name: matched.name });
      return;
    }
    reportUnknown.mutate({ path: { agency_id: agencyId }, query: { upc } });
  };

  useBarcodeScanner(scanBarcode);

  return (
    <div className="iq-search">
      <Panel>
        <ScanField
          value={query}
          onValueChange={setQuery}
          count={results.length > 0 ? resultCountLabel(results.length, allItems.length) : undefined}
        />
        <Results
          failed={items.isError}
          loading={items.isPending}
          query={query}
          results={results}
          total={allItems.length}
          onPick={onPick}
        />
      </Panel>
    </div>
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

  return (
    <ul className="iq-results">
      {results.map((item) => (
        <ItemRow key={item.id} item={item} onPick={(picked) => onPick({ id: picked.id, name: picked.name })} />
      ))}
    </ul>
  );
}
