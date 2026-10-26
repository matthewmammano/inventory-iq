import { MINUS_LABEL, PLUS_LABEL } from "../constants";

import "./Stepper.css";

type StepperProps = {
  value: number;
  min: number;
  steps: readonly number[];
  onChange: (next: number) => void;
};

/** The quantity control: a minus side, the running number, a plus side, all three the same size. */
export function Stepper({ value, min, steps, onChange }: StepperProps) {
  const nudge = (by: number) => onChange(Math.max(min, value + by));

  return (
    <div className="iq-stepper">
      <StepSide sign={-1} steps={steps} onNudge={nudge} />
      <output className="iq-step iq-step-count">{value}</output>
      <StepSide sign={1} steps={steps} onNudge={nudge} />
    </div>
  );
}

type StepSideProps = {
  sign: 1 | -1;
  steps: readonly number[];
  onNudge: (by: number) => void;
};

/** One side of the control. A single step reads as a bare sign, several read as the amounts themselves. */
function StepSide({ sign, steps, onNudge }: StepSideProps) {
  const sole = sign < 0 ? MINUS_LABEL : PLUS_LABEL;
  const tone = sign < 0 ? "iq-step-minus" : "iq-step-plus";

  return (
    <div className="iq-step-stack">
      {steps.map((step) => (
        <button
          key={step}
          type="button"
          className={`iq-step ${tone}`}
          onClick={() => onNudge(sign * step)}
        >
          {steps.length === 1 ? sole : `${sole}${step}`}
        </button>
      ))}
    </div>
  );
}
