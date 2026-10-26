import { Loading, Stack } from "@usefragments/ui";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";

import { getApiV1AgenciesByAgencyIdStoragesOptions } from "../../../api/@tanstack/react-query.gen";
import type { ScanStorageOptionsResponse } from "../../../api/types.gen";
import { ChoiceCard } from "../../../components/ChoiceCard";
import { ClipboardCheck } from "../../../components/icons/ClipboardCheck";
import { Circle } from "../../../components/icons/Circle";
import { Hand } from "../../../components/icons/Hand";
import { PackagePlus } from "../../../components/icons/PackagePlus";
import { Note } from "../../../components/Note";
import { StepBar } from "../../../components/StepBar";
import {
  CONTINUE_LABEL,
  COUNT_STORAGE_ID,
  FROM_GROUP_LABEL,
  LOADING_STORAGES_LABEL,
  LOAD_FAILED_NOTE,
  NO_FROM_NOTE,
  NO_TO_NOTE,
  PICK_FROM_PROMPT,
  PICK_TO_PROMPT,
  RESTOCK_STORAGE_ID,
  TAKE_STORAGE_ID,
  TO_GROUP_LABEL,
} from "../../../constants";
import {
  fromIdForTo,
  routeChoices,
  soleFromId,
  soleRoute,
  soleToId,
  type ScanChoice,
  type ScanRoute,
} from "../routeChoices";

import "./PickRoute.css";

type PickRouteProps = {
  agencyId: number;
  locationId: number;
  onPicked: (route: ScanRoute, autoPassed: boolean) => void;
};

/** The second step: which shelf the stock leaves, and which one it lands on. */
export function PickRoute({ agencyId, locationId, onPicked }: PickRouteProps) {
  const storages = useQuery(
    getApiV1AgenciesByAgencyIdStoragesOptions({ path: { agency_id: agencyId }, query: { location_id: locationId } }),
  );

  if (storages.isError) return <Note>{LOAD_FAILED_NOTE}</Note>;
  if (storages.isPending) return <Loading label={LOADING_STORAGES_LABEL} />;

  return <RouteForm options={storages.data} onPicked={onPicked} />;
}

type RouteFormProps = {
  options: ScanStorageOptionsResponse;
  onPicked: (route: ScanRoute, autoPassed: boolean) => void;
};

function RouteForm({ options, onPicked }: RouteFormProps) {
  const [from, setFrom] = useState(() => soleFromId(options));
  const [to, setTo] = useState(() => soleToId(options, soleFromId(options)));
  const skipped = soleRoute(options);

  useEffect(() => {
    if (skipped) onPicked(skipped, true);
  }, [skipped, onPicked]);

  if (skipped) return <Loading label={LOADING_STORAGES_LABEL} />;

  const choices = routeChoices(options, from);
  const pickFrom = (id: number) => {
    setFrom(id);
    setTo(soleToId(options, id));
  };
  const pickTo = (id: number) => {
    setTo(id);
    setFrom(fromIdForTo(options, id, from));
  };

  return (
    <Stack gap="md">
      <div className="iq-route-groups">
        <ChoiceGroup
          step={1}
          label={FROM_GROUP_LABEL}
          emptyNote={NO_FROM_NOTE}
          choices={choices.from}
          picked={from}
          onPick={pickFrom}
        />
        <ChoiceGroup
          step={2}
          label={TO_GROUP_LABEL}
          emptyNote={NO_TO_NOTE}
          choices={choices.to}
          picked={to}
          onPick={pickTo}
        />
      </div>
      <StepBar
        summary={from === null ? PICK_FROM_PROMPT : to === null ? PICK_TO_PROMPT : choices.summary(from, to)}
        actionLabel={CONTINUE_LABEL}
        disabled={from === null || to === null}
        onAction={() => from !== null && to !== null && onPicked({ fromStorageId: from, toStorageId: to }, false)}
      />
    </Stack>
  );
}

const ACTION_ICONS: Record<number, ReactNode> = {
  [RESTOCK_STORAGE_ID]: <PackagePlus />,
  [COUNT_STORAGE_ID]: <ClipboardCheck />,
  [TAKE_STORAGE_ID]: <Hand />,
};

type ChoiceGroupProps = {
  step: number;
  label: string;
  emptyNote: string;
  choices: ScanChoice[];
  picked: number | null;
  onPick: (id: number) => void;
};

function ChoiceGroup({ step, label, emptyNote, choices, picked, onPick }: ChoiceGroupProps) {
  return (
    <section className="iq-route-group">
      <h2 className="iq-route-group-label">
        <span className="iq-route-group-step">{step}</span>
        {label}
      </h2>
      {choices.length === 0 ? (
        <Note>{emptyNote}</Note>
      ) : (
        choices.map((choice) => (
          <ChoiceCard
            key={choice.id}
            label={choice.label}
            hint={choice.hint}
            icon={ACTION_ICONS[choice.id] ?? <Circle />}
            tone={choice.id in ACTION_ICONS ? "action" : "place"}
            selected={choice.id === picked}
            onSelect={() => onPick(choice.id)}
          />
        ))
      )}
    </section>
  );
}
