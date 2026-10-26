import "./Button.css";

type ButtonProps = {
  children: string;
  variant?: "primary" | "quiet";
  disabled?: boolean;
  onClick: () => void;
};

/** Every screen's action button. `primary` carries the step forward, `quiet` undoes or steps aside. */
export function Button({ children, variant = "primary", disabled, onClick }: ButtonProps) {
  return (
    <button type="button" className={`iq-button iq-button-${variant}`} disabled={disabled} onClick={onClick}>
      {children}
    </button>
  );
}
