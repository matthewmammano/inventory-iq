import { useEffect, type CSSProperties } from "react";

import { TOAST_ICONS, TOAST_VISIBLE_MS } from "../constants";

import "./Toast.css";

export type ToastTone = "success" | "warning" | "error";

export type ToastMessage = { tone: ToastTone; text: string };

/** The countdown ring reads its length from the same constant the hide timer uses. */
const COUNTDOWN = { "--iq-toast-duration": `${TOAST_VISIBLE_MS}ms` } as CSSProperties;

type ToastProps = {
  message: ToastMessage | null;
  onHide: () => void;
};

/** The bar that slides up from the bottom to confirm what just happened, then leaves on its own. */
export function Toast({ message, onHide }: ToastProps) {
  useEffect(() => {
    if (message === null) return;
    const timer = window.setTimeout(onHide, TOAST_VISIBLE_MS);
    return () => window.clearTimeout(timer);
  }, [message, onHide]);

  if (message === null) return null;

  return (
    <div className={`iq-toast iq-toast-${message.tone}`} role="status" style={COUNTDOWN}>
      <span className="iq-toast-icon" aria-hidden="true">
        {TOAST_ICONS[message.tone]}
      </span>
      <p className="iq-toast-text">{message.text}</p>
      <span className="iq-toast-timer" aria-hidden="true" />
    </div>
  );
}
