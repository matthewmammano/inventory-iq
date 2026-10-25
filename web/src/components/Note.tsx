import { EmptyState } from "@usefragments/ui";

import "./Note.css";

type NoteProps = {
  children: string;
};

/** The one-line message that stands in for a result list: nothing stocked, nothing matched, nothing loaded. */
export function Note({ children }: NoteProps) {
  return (
    <div className="iq-note">
      <EmptyState>
        <EmptyState.Title>{children}</EmptyState.Title>
      </EmptyState>
    </div>
  );
}
