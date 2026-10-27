import type { ComponentPropsWithoutRef } from "react";

import "./Button.css";

type ButtonShape = {
  children: string;
  variant?: "primary" | "quiet";
  size?: "regular" | "small";
  disabled?: boolean;
};

/** A plain button carries its own click; a form's button is the one Enter presses, so it owns no click. */
type ButtonProps = ButtonShape &
  Omit<ComponentPropsWithoutRef<"button">, keyof ButtonShape | "type" | "onClick" | "className"> &
  ({ type?: "button"; onClick: () => void } | { type: "submit"; onClick?: never });

/** Every screen's action button. `primary` carries the step forward, `quiet` undoes or steps aside. */
export function Button({
  children,
  variant = "primary",
  size = "regular",
  type = "button",
  disabled,
  onClick,
  ...rest
}: ButtonProps) {
  return (
    <button
      {...rest}
      type={type}
      className={`iq-button iq-button-${variant} iq-button-${size}`}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  );
}
