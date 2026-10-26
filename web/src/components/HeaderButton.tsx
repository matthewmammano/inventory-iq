import type { ReactNode } from "react";

import "./HeaderButton.css";

type HeaderButtonProps = {
  label: string;
  href?: string;
  onClick?: () => void;
  children: ReactNode;
};

/** One control in the top bar. Every one looks the same, so the icon and label carry the meaning. */
export function HeaderButton({ label, href, onClick, children }: HeaderButtonProps) {
  const className = "iq-header-button";

  if (href !== undefined) {
    return (
      <a className={className} href={href} aria-label={label}>
        {children}
      </a>
    );
  }
  return (
    <button type="button" className={className} aria-label={label} onClick={onClick}>
      {children}
    </button>
  );
}
