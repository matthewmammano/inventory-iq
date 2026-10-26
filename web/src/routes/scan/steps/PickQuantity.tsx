import { Loading } from "@usefragments/ui";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { getApiV1AgenciesByAgencyIdItemsByItemIdScanContextOptions } from "../../../api/@tanstack/react-query.gen";
import type { ScanContextResponse } from "../../../api/types.gen";
import { Button } from "../../../components/Button";
import { ItemPhoto } from "../../../components/ItemPhoto";
import { Note } from "../../../components/Note";
import { Panel } from "../../../components/Panel";
import { RouteStrip } from "../../../components/RouteStrip";
import { Stepper } from "../../../components/Stepper";
import {
  CONTINUE_TO_DATES_LABEL,
  LOADING_ITEM_LABEL,
  LOAD_FAILED_NOTE,
  QUICK_ADJUST_STEPS,
  RESET_QUANTITY_LABEL,
  SAVE_SCAN_LABEL,
  SINGLE_STEP,
  STALE_COUNT_NOTE,
  suggestedRestockNote,
} from "../../../constants";
import type { ScanRoute } from "../routeChoices";

import "./PickQuantity.css";

type PickQuantityProps = {
  agencyId: number;
  itemId: number;
  route: ScanRoute;
  onPicked: (quantity: number, context: ScanContextResponse) => void;
};

/** The third step: how many units this scan moves. */
export function PickQuantity({ agencyId, itemId, route, onPicked }: PickQuantityProps) {
  const context = useQuery(
    getApiV1AgenciesByAgencyIdItemsByItemIdScanContextOptions({
      path: { agency_id: agencyId, item_id: itemId },
      query: { from_storage_id: route.fromStorageId, to_storage_id: route.toStorageId },
    }),
  );

  if (context.isError) return <Note>{LOAD_FAILED_NOTE}</Note>;
  if (context.isPending) return <Loading label={LOADING_ITEM_LABEL} />;

  return <QuantityForm context={context.data} onPicked={onPicked} />;
}

type QuantityFormProps = {
  context: ScanContextResponse;
  onPicked: (quantity: number, context: ScanContextResponse) => void;
};

function QuantityForm({ context, onPicked }: QuantityFormProps) {
  const [quantity, setQuantity] = useState(context.minimum_quantity);

  return (
    <div className="iq-quantity">
      <Panel>
        <RouteStrip from={context.from_label} to={context.to_label} />
        <div className="iq-quantity-item">
          <ItemPhoto src={context.image_url} name={context.item_name} />
          <div className="iq-quantity-facts">
            {context.increments ? <p className="iq-quantity-unit">{context.increments}</p> : null}
            <h2 className="iq-quantity-name">{context.item_name}</h2>
            <QuantityHint context={context} />
          </div>
        </div>
        <Stepper
          value={quantity}
          min={context.minimum_quantity}
          steps={context.quick_adjust ? QUICK_ADJUST_STEPS : SINGLE_STEP}
          onChange={setQuantity}
        />
        <div className="iq-quantity-actions">
          <Button
            variant="quiet"
            disabled={quantity === context.minimum_quantity}
            onClick={() => setQuantity(context.minimum_quantity)}
          >
            {RESET_QUANTITY_LABEL}
          </Button>
          <Button onClick={() => onPicked(quantity, context)}>
            {context.expiration_tracking ? CONTINUE_TO_DATES_LABEL : SAVE_SCAN_LABEL}
          </Button>
        </div>
      </Panel>
    </div>
  );
}

/** Only the more urgent of the two shelf hints shows, so the screen never nags twice. */
function QuantityHint({ context }: { context: ScanContextResponse }) {
  if (context.stale_count) return <p className="iq-quantity-hint">{STALE_COUNT_NOTE}</p>;
  if (context.suggested_restock) {
    return <p className="iq-quantity-hint">{suggestedRestockNote(context.suggested_restock)}</p>;
  }
  return null;
}
