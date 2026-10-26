import { Main } from "@usefragments/ui";
import type { ReactNode } from "react";

import { BACK_LABEL } from "../constants";
import { HeaderButton } from "./HeaderButton";
import { ArrowLeft } from "./icons/ArrowLeft";

import "./Page.css";

/** Wide is the working width: every screen built out of buttons or typing gets it. */
export type PageWidth = "wide" | "reading";

type PageProps = {
  title: string;
  subtitle?: string;
  width?: PageWidth;
  logoUrl?: string;
  actions?: ReactNode;
  onBack?: () => void;
  children: ReactNode;
};

/** Every screen's frame: the agency's bar on top, its controls on the right, one measure below. */
export function Page({ title, subtitle, width = "wide", logoUrl, actions, onBack, children }: PageProps) {
  return (
    <>
      <header className="iq-header">
        {logoUrl ? <img className="iq-page-logo" src={logoUrl} alt="" /> : null}
        <span className="iq-page-heading">
          <h1 className="iq-page-title">{title}</h1>
          {subtitle ? <p className="iq-page-subtitle">{subtitle}</p> : null}
        </span>
        <span className="iq-header-actions">
          {actions}
          {onBack ? (
            <HeaderButton label={BACK_LABEL} onClick={onBack}>
              <ArrowLeft />
              {BACK_LABEL}
            </HeaderButton>
          ) : null}
        </span>
      </header>
      <Main>
        <Main.Content>
          <div className={`iq-page-body iq-page-body-${width}`}>{children}</div>
        </Main.Content>
      </Main>
    </>
  );
}
