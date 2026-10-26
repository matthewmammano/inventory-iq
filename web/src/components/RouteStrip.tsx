import { FROM_STRIP_LABEL, TO_STRIP_LABEL } from "../constants";

import "./RouteStrip.css";

type RouteStripProps = {
  from: string;
  to: string;
};

/** The standing reminder of which way this scan moves stock. */
export function RouteStrip({ from, to }: RouteStripProps) {
  return (
    <dl className="iq-route-strip">
      <div className="iq-route-leg">
        <dt>{FROM_STRIP_LABEL}</dt>
        <dd>{from}</dd>
      </div>
      <div className="iq-route-leg">
        <dt>{TO_STRIP_LABEL}</dt>
        <dd>{to}</dd>
      </div>
    </dl>
  );
}
