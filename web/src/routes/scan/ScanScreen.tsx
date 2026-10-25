import { IconButton, Loading, Stack } from "@usefragments/ui";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import {
  getApiV1AgenciesByAgencyIdItemsOptions,
  getApiV1MeOptions,
} from "../../api/@tanstack/react-query.gen";
import { ItemRow } from "../../components/ItemRow";
import { Note } from "../../components/Note";
import { Page } from "../../components/Page";
import { ScanField } from "../../components/ScanField";
import { KeyRound } from "../../components/icons/KeyRound";
import {
  ADMIN_LINK_LABEL,
  LOADING_ITEMS_LABEL,
  LOAD_FAILED_NOTE,
  NO_ITEMS_NOTE,
  SCAN_SCREEN_SUBTITLE,
  SCAN_SCREEN_TITLE,
  noMatchNote,
  resultCountLabel,
} from "../../constants";
import { useBarcodeScanner } from "../../hooks/useBarcodeScanner";
import { adminLoginUrl, scanItemUrl, unknownBarcodeUrl } from "../../lib/urls";
import { findByBarcode, looksLikeBarcode, searchItems } from "./itemSearch";

export function ScanScreen() {
  const [query, setQuery] = useState("");
  const agency = useQuery(getApiV1MeOptions());
  const agencyId = agency.data?.id;
  const items = useQuery({
    ...getApiV1AgenciesByAgencyIdItemsOptions({ path: { agency_id: agencyId ?? 0 } }),
    enabled: agencyId !== undefined,
  });

  const allItems = useMemo(() => items.data ?? [], [items.data]);
  const results = useMemo(() => searchItems(allItems, query), [allItems, query]);

  const openScan = (itemId: number) => {
    if (agencyId === undefined) return;
    window.location.assign(scanItemUrl(agencyId, itemId));
  };

  const scanBarcode = (upc: string) => {
    if (agencyId === undefined) return;
    const matched = findByBarcode(allItems, upc);
    window.location.assign(matched ? scanItemUrl(agencyId, matched.id) : unknownBarcodeUrl(agencyId, upc));
  };

  useBarcodeScanner(scanBarcode);

  const typeQuery = (value: string) => {
    if (looksLikeBarcode(value)) {
      scanBarcode(value);
      return;
    }
    setQuery(value);
  };

  return (
    <Page
      title={SCAN_SCREEN_TITLE}
      subtitle={SCAN_SCREEN_SUBTITLE}
      logoUrl={agency.data?.logo_url}
      actions={
        agencyId === undefined ? null : (
          <IconButton aria-label={ADMIN_LINK_LABEL} render={<a href={adminLoginUrl(agencyId)} />}>
            <KeyRound />
          </IconButton>
        )
      }
    >
      <Stack gap="md">
        <ScanField
          value={query}
          onValueChange={typeQuery}
          count={results.length > 0 ? resultCountLabel(results.length, allItems.length) : undefined}
        />
        <Results
          failed={agency.isError || items.isError}
          loading={agency.isPending || items.isPending}
          query={query}
          results={results}
          total={allItems.length}
          onPick={openScan}
        />
      </Stack>
    </Page>
  );
}

type ResultsProps = {
  failed: boolean;
  loading: boolean;
  query: string;
  results: ReturnType<typeof searchItems>;
  total: number;
  onPick: (itemId: number) => void;
};

function Results({ failed, loading, query, results, total, onPick }: ResultsProps) {
  if (failed) return <Note>{LOAD_FAILED_NOTE}</Note>;
  if (loading) return <Loading label={LOADING_ITEMS_LABEL} />;
  if (total === 0) return <Note>{NO_ITEMS_NOTE}</Note>;
  if (results.length === 0) return <Note>{noMatchNote(query)}</Note>;

  return (
    <ul className="iq-results">
      {results.map((item) => (
        <ItemRow key={item.id} item={item} onPick={(picked) => onPick(picked.id)} />
      ))}
    </ul>
  );
}
