import { useEffect, type ReactNode } from "react";

import { Delete } from "./icons/Delete";
import {
  KEYPAD_CLEAR_LABEL,
  KEYPAD_DELETE_LABEL,
  KEYPAD_DIGITS,
  KEYPAD_ZERO,
  pinProgressLabel,
} from "../constants";

import "./Keypad.css";

const DIGIT_KEY = /^[0-9]$/;

type KeypadProps = {
  value: string;
  length: number;
  onValueChange: (value: string) => void;
  onSubmit: () => void;
};

/** A numeric entry built for tapping, so a kiosk never needs a keyboard, and keys still answer one. */
export function Keypad({ value, length, onValueChange, onSubmit }: KeypadProps) {
  const append = (digit: string) => onValueChange((value + digit).slice(0, length));
  const dropLast = () => onValueChange(value.slice(0, -1));
  const full = value.length >= length;

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Enter") onSubmit();
      else if (event.key === "Backspace") onValueChange(value.slice(0, -1));
      else if (event.key === "Escape") onValueChange("");
      else if (DIGIT_KEY.test(event.key)) onValueChange((value + event.key).slice(0, length));
      else return;
      event.preventDefault();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [value, length, onValueChange, onSubmit]);

  return (
    <div className="iq-keypad">
      <output className="iq-keypad-entry" aria-label={pinProgressLabel(value.length, length)}>
        {Array.from({ length }, (_, slot) => (
          <span key={slot} className="iq-keypad-slot">
            {slot < value.length ? <span className="iq-keypad-dot" /> : null}
          </span>
        ))}
      </output>
      <div className="iq-keypad-keys">
        {KEYPAD_DIGITS.map((digit) => (
          <Key key={digit} label={digit} tone="digit" disabled={full} onPress={() => append(digit)} />
        ))}
        <Key
          label={KEYPAD_CLEAR_LABEL}
          tone="word"
          disabled={value.length === 0}
          onPress={() => onValueChange("")}
        />
        <Key label={KEYPAD_ZERO} tone="digit" disabled={full} onPress={() => append(KEYPAD_ZERO)} />
        <Key
          label={KEYPAD_DELETE_LABEL}
          tone="word"
          icon={<Delete />}
          disabled={value.length === 0}
          onPress={dropLast}
        />
      </div>
    </div>
  );
}

type KeyProps = {
  label: string;
  tone: "digit" | "word";
  icon?: ReactNode;
  disabled: boolean;
  onPress: () => void;
};

/** An icon key keeps its label for screen readers only; a word key shows it. */
function Key({ label, tone, icon, disabled, onPress }: KeyProps) {
  return (
    <button
      type="button"
      className={`iq-keypad-key iq-keypad-key-${tone}`}
      aria-label={icon ? label : undefined}
      disabled={disabled}
      onClick={onPress}
    >
      {icon ?? label}
    </button>
  );
}
