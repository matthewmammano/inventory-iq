import type { ReactNode } from "react";

import "./ChoiceCard.css";

/** An action is something you do; a place is somewhere stock sits. The icon says which. */
export type ChoiceTone = "action" | "place";

type ChoiceCardProps = {
  label: string;
  hint?: string;
  icon: ReactNode;
  tone: ChoiceTone;
  selected: boolean;
  onSelect: () => void;
};

/** One big tappable choice, with its icon in the same spot so every label starts on one line. */
export function ChoiceCard({ label, hint, icon, tone, selected, onSelect }: ChoiceCardProps) {
  return (
    <button type="button" className={`iq-choice iq-choice-${tone}`} aria-pressed={selected} onClick={onSelect}>
      <span className="iq-choice-icon">{icon}</span>
      <span className="iq-choice-text">
        <span className="iq-choice-label">{label}</span>
        {hint ? <span className="iq-choice-hint">{hint}</span> : null}
      </span>
    </button>
  );
}
