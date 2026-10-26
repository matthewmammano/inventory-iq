import { Button } from "./Button";

import "./StepBar.css";

type StepBarProps = {
  summary: string;
  actionLabel: string;
  disabled?: boolean;
  onAction: () => void;
};

/** The bar every flow step ends with: what you picked on the left, the way forward on the right. */
export function StepBar({ summary, actionLabel, disabled, onAction }: StepBarProps) {
  return (
    <div className="iq-step-bar">
      <p className="iq-step-summary">{summary}</p>
      <Button disabled={disabled} onClick={onAction}>
        {actionLabel}
      </Button>
    </div>
  );
}
