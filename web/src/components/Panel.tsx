import type { ReactNode } from "react";

import "./Panel.css";

type PanelProps = {
  children: ReactNode;
};

/** The bordered surface a screen's contents sit on, with one gap between its rows. */
export function Panel({ children }: PanelProps) {
  return <section className="iq-panel">{children}</section>;
}
