import { Loading, Stack } from "@usefragments/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  getApiV1AgenciesByAgencyIdDeviceLocationQueryKey,
  getApiV1AgenciesByAgencyIdLocationsOptions,
  putApiV1AgenciesByAgencyIdDeviceLocationMutation,
} from "../../../api/@tanstack/react-query.gen";
import { ChoiceCard } from "../../../components/ChoiceCard";
import { Circle } from "../../../components/icons/Circle";
import { Note } from "../../../components/Note";
import { StepBar } from "../../../components/StepBar";
import {
  CONTINUE_LABEL,
  LOADING_LOCATIONS_LABEL,
  LOAD_FAILED_NOTE,
  NO_LOCATIONS_NOTE,
  PICK_LOCATION_PROMPT,
} from "../../../constants";

type PickLocationProps = {
  agencyId: number;
  onPicked: (locationId: number) => void;
};

/** Asked once per device, then remembered for a year, so the pick gets a confirming button. */
export function PickLocation({ agencyId, onPicked }: PickLocationProps) {
  const [picked, setPicked] = useState<number | null>(null);
  const locations = useQuery(getApiV1AgenciesByAgencyIdLocationsOptions({ path: { agency_id: agencyId } }));
  const bind = useMutation(putApiV1AgenciesByAgencyIdDeviceLocationMutation());
  const queries = useQueryClient();

  const all = locations.data ?? [];
  const pickedName = all.find((location) => location.id === picked)?.name;

  const save = () => {
    if (picked === null) return;
    bind.mutate(
      { path: { agency_id: agencyId }, body: { location_id: picked } },
      {
        onSuccess: () => {
          queries.setQueryData(
            getApiV1AgenciesByAgencyIdDeviceLocationQueryKey({ path: { agency_id: agencyId } }),
            { location_id: picked },
          );
          onPicked(picked);
        },
      },
    );
  };

  if (locations.isError) return <Note>{LOAD_FAILED_NOTE}</Note>;
  if (locations.isPending) return <Loading label={LOADING_LOCATIONS_LABEL} />;
  if (all.length === 0) return <Note>{NO_LOCATIONS_NOTE}</Note>;

  return (
    <Stack gap="md">
      <div className="iq-choice-list">
        {all.map((location) => (
          <ChoiceCard
            key={location.id}
            label={location.name}
            icon={<Circle />}
            tone="place"
            selected={location.id === picked}
            onSelect={() => setPicked(location.id)}
          />
        ))}
      </div>
      <StepBar
        summary={pickedName ?? PICK_LOCATION_PROMPT}
        actionLabel={CONTINUE_LABEL}
        disabled={picked === null || bind.isPending}
        onAction={save}
      />
    </Stack>
  );
}
