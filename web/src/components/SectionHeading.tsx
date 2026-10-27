import { ChevronRight } from "./icons/ChevronRight";

import "./SectionHeading.css";

type SectionHeadingProps = {
  label: string;
  actionLabel: string;
  onAction: () => void;
};

/** A quiet label over a list, with one optional control on the far side that opens the long version. */
export function SectionHeading({ label, actionLabel, onAction }: SectionHeadingProps) {
  return (
    <div className="iq-section-heading">
      <h2 className="iq-section-label">{label}</h2>
      <button type="button" className="iq-section-action" onClick={onAction}>
        {actionLabel}
        <ChevronRight />
      </button>
    </div>
  );
}
