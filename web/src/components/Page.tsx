import { Main } from "@usefragments/ui";
import type { ReactNode } from "react";

import "./Page.css";

type PageProps = {
  title: string;
  subtitle?: string;
  logoUrl?: string;
  actions?: ReactNode;
  children: ReactNode;
};

/** Every screen's frame: the agency's bar on top, one gutter and measure below it. */
export function Page({ title, subtitle, logoUrl, actions, children }: PageProps) {
  return (
    <>
      <header className="iq-header">
        {logoUrl ? <img className="iq-page-logo" src={logoUrl} alt="" /> : null}
        <span className="iq-page-heading">
          <h1 className="iq-page-title">{title}</h1>
          {subtitle ? <p className="iq-page-subtitle">{subtitle}</p> : null}
        </span>
        {actions ? <span className="iq-header-actions">{actions}</span> : null}
      </header>
      <Main>
        <Main.Content>
          <div className="iq-page-body">{children}</div>
        </Main.Content>
      </Main>
    </>
  );
}
