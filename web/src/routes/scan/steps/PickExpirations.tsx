import { Loading } from "@usefragments/ui";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { getApiV1AgenciesByAgencyIdItemsByItemIdExpirationsOptions } from "../../../api/@tanstack/react-query.gen";
import type { ExpirationEntryResponse } from "../../../api/types.gen";
import { Note } from "../../../components/Note";
import { StepBar } from "../../../components/StepBar";
import { Stepper } from "../../../components/Stepper";
import {
  ADD_DATE_LABEL,
  AVAILABLE_COLUMN_LABEL,
  EXPIRATION_COLUMN_LABEL,
  LOADING_DATES_LABEL,
  LOAD_FAILED_NOTE,
  NEW_DATE_LABEL,
  OTHER_DATE_LABEL,
  OVER_DATED_LABEL,
  SAVE_SCAN_LABEL,
  SELECTED_COLUMN_LABEL,
  SINGLE_STEP,
  datedProgressLabel,
} from "../../../constants";
import type { ScanRoute } from "../routeChoices";
import { allocationsOf, datedTotal, isComplete, type DateEntry } from "../expirationAllocations";

import "./PickExpirations.css";

export type ExpirationAllocation = { expires_on: string | null; quantity: number };

type PickExpirationsProps = {
  agencyId: number;
  itemId: number;
  route: ScanRoute;
  quantity: number;
  onDone: (allocations: ExpirationAllocation[]) => void;
};

/** The last step for a dated item: which lots the quantity comes out of, or goes onto. */
export function PickExpirations({ agencyId, itemId, route, quantity, onDone }: PickExpirationsProps) {
  const entry = useQuery(
    getApiV1AgenciesByAgencyIdItemsByItemIdExpirationsOptions({
      path: { agency_id: agencyId, item_id: itemId },
      query: { from_storage_id: route.fromStorageId, to_storage_id: route.toStorageId, quantity },
    }),
  );

  if (entry.isError) return <Note>{LOAD_FAILED_NOTE}</Note>;
  if (entry.isPending) return <Loading label={LOADING_DATES_LABEL} />;

  return <AllocationForm entry={entry.data} onDone={onDone} />;
}

type AllocationFormProps = {
  entry: ExpirationEntryResponse;
  onDone: (allocations: ExpirationAllocation[]) => void;
};

function AllocationForm({ entry, onDone }: AllocationFormProps) {
  const [known, setKnown] = useState<DateEntry[]>(
    entry.options.map((option) => ({ expiresOn: option.expires_on, quantity: option.default_quantity })),
  );
  const [added, setAdded] = useState<DateEntry[]>([]);
  const [other, setOther] = useState(0);

  const total = datedTotal(known, added, other);
  const over = total > entry.target_quantity;

  const setAt = (list: DateEntry[], index: number, patch: Partial<DateEntry>) =>
    list.map((row, at) => (at === index ? { ...row, ...patch } : row));

  return (
    <div className={over ? "iq-dates iq-fit iq-dates-over" : "iq-dates iq-fit"}>
      <header className="iq-dates-heading">
        <h2 className="iq-dates-title">
          {entry.item_name} - {entry.storage_name}
        </h2>
        <p className="iq-dates-subtitle">{entry.subtitle}</p>
      </header>

      <div className="iq-dates-list iq-scroll">
        <div className="iq-dates-head">
          <span>{EXPIRATION_COLUMN_LABEL}</span>
          <span className="iq-dates-head-number">{AVAILABLE_COLUMN_LABEL}</span>
          <span className="iq-dates-head-number">{SELECTED_COLUMN_LABEL}</span>
        </div>

        {entry.options.map((option, index) => (
          <AllocationRow
            key={option.expires_on}
            label={option.expires_on}
            available={option.quantity}
            suggested={option.suggested}
            value={known[index].quantity}
            onChange={(next) => setKnown(setAt(known, index, { quantity: next }))}
          />
        ))}

        {added.map((row, index) => (
          <AllocationRow
            key={`added-${index}`}
            label={NEW_DATE_LABEL}
            value={row.quantity}
            onChange={(next) => setAdded(setAt(added, index, { quantity: next }))}
            date={row.expiresOn ?? ""}
            onDateChange={(next) => setAdded(setAt(added, index, { expiresOn: next }))}
          />
        ))}

        {entry.allows_new_dates && added.length < entry.max_new_rows ? (
          <button
            type="button"
            className="iq-dates-add"
            onClick={() => setAdded([...added, { expiresOn: "", quantity: 0 }])}
          >
            {ADD_DATE_LABEL}
          </button>
        ) : null}

        {entry.allows_other ? (
          <AllocationRow label={OTHER_DATE_LABEL} value={other} onChange={setOther} />
        ) : null}
      </div>

      <StepBar
        summary={datedProgressLabel(total, entry.target_quantity)}
        actionLabel={over ? OVER_DATED_LABEL : SAVE_SCAN_LABEL}
        disabled={!isComplete(entry, total, added)}
        onAction={() => onDone(allocationsOf(known, added, other))}
      />
    </div>
  );
}

type AllocationRowProps = {
  label: string;
  available?: number;
  suggested?: boolean;
  value: number;
  onChange: (next: number) => void;
  date?: string;
  onDateChange?: (next: string) => void;
};

function AllocationRow({ label, available, suggested, value, onChange, date, onDateChange }: AllocationRowProps) {
  return (
    <div className="iq-dates-row">
      <div className="iq-dates-row-label">
        {onDateChange ? (
          <input
            type="date"
            className="iq-dates-input"
            aria-label={label}
            value={date}
            onChange={(event) => onDateChange(event.target.value)}
          />
        ) : (
          <span className="iq-dates-row-name">{label}</span>
        )}
        {suggested ? <span className="iq-dates-row-suggested">earliest</span> : null}
      </div>
      <span className="iq-dates-row-available">{available ?? ""}</span>
      <Stepper value={value} min={0} steps={SINGLE_STEP} onChange={onChange} />
    </div>
  );
}
