import { Loading } from "@usefragments/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  getApiV1AgenciesByAgencyIdDeviceLocationOptions,
  getApiV1AgenciesByAgencyIdLocationsOptions,
  getApiV1AgenciesByAgencyIdStoragesOptions,
  getApiV1MeOptions,
  postApiV1AgenciesByAgencyIdScansMutation,
} from "../../api/@tanstack/react-query.gen";
import type { ScanContextResponse, ScanResultResponse } from "../../api/types.gen";
import { Note } from "../../components/Note";
import { HeaderButton } from "../../components/HeaderButton";
import { Page, type PageWidth } from "../../components/Page";
import { Toast, type ToastMessage } from "../../components/Toast";
import { KeyRound } from "../../components/icons/KeyRound";
import {
  ADMIN_LINK_LABEL,
  EXPIRATION_STEP_TITLE,
  LOADING_ITEMS_LABEL,
  LOAD_FAILED_NOTE,
  LOCATION_STEP_SUBTITLE,
  LOCATION_STEP_TITLE,
  QUANTITY_STEP_SUBTITLE,
  QUANTITY_STEP_TITLE,
  ROUTE_STEP_SUBTITLE,
  ROUTE_STEP_TITLE,
  SAVE_FAILED_NOTE,
  SCAN_SCREEN_SUBTITLE,
  SCAN_SCREEN_TITLE,
  initialCountNote,
  scanSavedNote,
} from "../../constants";
import { adminLoginUrl } from "../../lib/urls";
import type { ScanRoute } from "./routeChoices";
import { PickExpirations, type ExpirationAllocation } from "./steps/PickExpirations";
import { PickItem, type PickedItem } from "./steps/PickItem";
import { PickLocation } from "./steps/PickLocation";
import { PickQuantity } from "./steps/PickQuantity";
import { PickRoute } from "./steps/PickRoute";

type Step = "item" | "location" | "route" | "quantity" | "dates";

type Draft = {
  item: PickedItem | null;
  locationId: number | null;
  route: ScanRoute | null;
  routeAutoPassed: boolean;
  quantity: number;
};

const EMPTY_DRAFT: Draft = {
  item: null,
  locationId: null,
  route: null,
  routeAutoPassed: false,
  quantity: 0,
};

const HEADINGS: Record<Step, { title: string; subtitle?: string; width?: PageWidth }> = {
  item: { title: SCAN_SCREEN_TITLE, subtitle: SCAN_SCREEN_SUBTITLE, width: "reading" },
  location: { title: LOCATION_STEP_TITLE, subtitle: LOCATION_STEP_SUBTITLE },
  route: { title: ROUTE_STEP_TITLE, subtitle: ROUTE_STEP_SUBTITLE },
  quantity: { title: QUANTITY_STEP_TITLE, subtitle: QUANTITY_STEP_SUBTITLE },
  dates: { title: EXPIRATION_STEP_TITLE },
};

/** A saved scan reads as one sentence, and the count warning rides along on it rather than as a second popup. */
function savedToast(result: ScanResultResponse): ToastMessage {
  if (!result.initial_count_required) return { tone: "success", text: scanSavedNote(result) };
  return { tone: "warning", text: `${scanSavedNote(result)} ${initialCountNote(result.item_name)}` };
}

/** The step after the item is always the same one, so its lists load while the person is still searching. */
function usePrefetchedNextStep(agencyId: number | undefined, locationId: number | null | undefined) {
  const queries = useQueryClient();
  useEffect(() => {
    if (agencyId === undefined || locationId === undefined) return;
    if (locationId === null) {
      queries.prefetchQuery(getApiV1AgenciesByAgencyIdLocationsOptions({ path: { agency_id: agencyId } }));
      return;
    }
    queries.prefetchQuery(
      getApiV1AgenciesByAgencyIdStoragesOptions({ path: { agency_id: agencyId }, query: { location_id: locationId } }),
    );
  }, [queries, agencyId, locationId]);
}

/** The whole guest scan: one route, one piece of state, four steps and a confirmation bar. */
export function ScanFlow() {
  const [step, setStep] = useState<Step>("item");
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [toast, setToast] = useState<ToastMessage | null>(null);

  const agency = useQuery(getApiV1MeOptions());
  const agencyId = agency.data?.id;
  const device = useQuery({
    ...getApiV1AgenciesByAgencyIdDeviceLocationOptions({ path: { agency_id: agencyId ?? 0 } }),
    enabled: agencyId !== undefined,
  });
  const save = useMutation(postApiV1AgenciesByAgencyIdScansMutation());

  const deviceLocationId = device.data?.location_id ?? null;
  usePrefetchedNextStep(agencyId, device.isSuccess ? deviceLocationId : undefined);

  const submit = (quantity: number, allocations: ExpirationAllocation[]) => {
    if (agencyId === undefined || draft.item === null || draft.route === null) return;
    save.mutate(
      {
        path: { agency_id: agencyId },
        body: {
          item_id: draft.item.id,
          counter_value: quantity,
          from_storage_id: draft.route.fromStorageId,
          to_storage_id: draft.route.toStorageId,
          expiration_allocations: allocations,
        },
      },
      {
        onSuccess: (result) => {
          setToast(savedToast(result));
          setDraft(EMPTY_DRAFT);
          setStep("item");
        },
      },
    );
  };

  const pickItem = (item: PickedItem) => {
    setDraft({ ...EMPTY_DRAFT, item, locationId: deviceLocationId });
    setStep(deviceLocationId === null ? "location" : "route");
  };

  const pickLocation = (locationId: number) => {
    setDraft((current) => ({ ...current, locationId }));
    setStep("route");
  };

  const pickRoute = (route: ScanRoute, autoPassed: boolean) => {
    setDraft((current) => ({ ...current, route, routeAutoPassed: autoPassed }));
    setStep("quantity");
  };

  const pickQuantity = (quantity: number, context: ScanContextResponse) => {
    setDraft((current) => ({ ...current, quantity }));
    if (context.expiration_tracking) {
      setStep("dates");
      return;
    }
    submit(quantity, []);
  };

  function backFrom(from: Step): Step | undefined {
    switch (from) {
      case "location":
        return "item";
      case "route":
        return deviceLocationId === null ? "location" : "item";
      case "quantity":
        return draft.routeAutoPassed ? backFrom("route") : "route";
      case "dates":
        return "quantity";
      default:
        return undefined;
    }
  }
  const backStep = backFrom(step);

  return (
    <>
      <Page
        {...HEADINGS[step]}
        logoUrl={agency.data?.logo_url}
        onBack={backStep ? () => setStep(backStep) : undefined}
        actions={
          step === "item" && agencyId !== undefined ? (
            <HeaderButton label={ADMIN_LINK_LABEL} href={adminLoginUrl(agencyId)}>
              <KeyRound />
            </HeaderButton>
          ) : null
        }
      >
        {save.isError ? <Note>{SAVE_FAILED_NOTE}</Note> : null}
        <Body
          agencyId={agencyId}
          failed={agency.isError}
          draft={draft}
          step={step}
          onSubmit={submit}
          handlers={{ pickItem, pickLocation, pickRoute, pickQuantity }}
        />
      </Page>
      <Toast message={toast} onHide={() => setToast(null)} />
    </>
  );
}

type Handlers = {
  pickItem: (item: PickedItem) => void;
  pickLocation: (locationId: number) => void;
  pickRoute: (route: ScanRoute, autoPassed: boolean) => void;
  pickQuantity: (quantity: number, context: ScanContextResponse) => void;
};

type BodyProps = {
  agencyId: number | undefined;
  failed: boolean;
  draft: Draft;
  step: Step;
  handlers: Handlers;
  onSubmit: (quantity: number, allocations: ExpirationAllocation[]) => void;
};

function Body({ agencyId, failed, draft, step, handlers, onSubmit }: BodyProps) {
  if (failed) return <Note>{LOAD_FAILED_NOTE}</Note>;
  if (agencyId === undefined) return <Loading label={LOADING_ITEMS_LABEL} />;

  switch (step) {
    case "item":
      return <PickItem agencyId={agencyId} onPick={handlers.pickItem} />;
    case "location":
      return <PickLocation agencyId={agencyId} onPicked={handlers.pickLocation} />;
    case "route":
      return draft.locationId === null ? (
        <Note>{LOAD_FAILED_NOTE}</Note>
      ) : (
        <PickRoute agencyId={agencyId} locationId={draft.locationId} onPicked={handlers.pickRoute} />
      );
    case "quantity":
      return draft.item === null || draft.route === null ? (
        <Note>{LOAD_FAILED_NOTE}</Note>
      ) : (
        <PickQuantity
          agencyId={agencyId}
          itemId={draft.item.id}
          route={draft.route}
          onPicked={handlers.pickQuantity}
        />
      );
    case "dates":
      return draft.item === null || draft.route === null ? (
        <Note>{LOAD_FAILED_NOTE}</Note>
      ) : (
        <PickExpirations
          agencyId={agencyId}
          itemId={draft.item.id}
          route={draft.route}
          quantity={draft.quantity}
          onDone={(allocations) => onSubmit(draft.quantity, allocations)}
        />
      );
  }
}
