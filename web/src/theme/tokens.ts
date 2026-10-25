import type { ThemeInputs } from "@usefragments/ui";

export const FONT_SANS = '"Nunito Sans", "Segoe UI", Calibri, sans-serif';
export const FONT_HEADING = '"Fira Sans", "Segoe UI", sans-serif';

/** Fragments ships desktop-SaaS density; a kiosk read by older volunteers needs body near 18px. */
export const KIOSK_SCALE = 1.15;

/** Smallest touch target on the kiosk, in pixels. */
export const TOUCH_TARGET_MIN = 46;

/**
 * The single source of truth for the look. Both departures from Fragments defaults
 * live here: `scale` for kiosk legibility, and the v1 amber brand in place of
 * their indigo.
 */
export const THEME: ThemeInputs = {
  brand: "#f4c95d",
  neutral: "oklch(0.5 0.02 85)",
  radius: 4,
  scale: KIOSK_SCALE,
  font: FONT_SANS,
  primaryChrome: "accent",
  danger: "#c32020",
  success: "#2f7d46",
  warning: "#a57210",
  info: "#4d73a6",
};
