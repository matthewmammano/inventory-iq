import { Field, Input, type InputType } from "@usefragments/ui";

import "./TextField.css";

type TextFieldProps = {
  id: string;
  label: string;
  type: InputType;
  value: string;
  autoComplete: string;
  onValueChange: (value: string) => void;
};

/** One labelled line of typing, sized for a kiosk rather than for a desktop form. */
export function TextField({ id, label, type, value, autoComplete, onValueChange }: TextFieldProps) {
  return (
    <Field className="iq-text-field">
      <Field.Label>{label}</Field.Label>
      <Input
        id={id}
        type={type}
        size="lg"
        value={value}
        autoComplete={autoComplete}
        onValueChange={onValueChange}
      />
    </Field>
  );
}
