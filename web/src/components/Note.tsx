import "./Note.css";

/** Quiet stands in for missing content; bad carries a refusal the person has to read and act on. */
export type NoteTone = "quiet" | "bad";

type NoteProps = {
  tone?: NoteTone;
  children: string;
};

/** The one message that stands in for a list: nothing stocked, nothing matched, nothing loaded. */
export function Note({ tone = "quiet", children }: NoteProps) {
  return (
    <p className={`iq-note iq-note-${tone}`} role="status">
      {children}
    </p>
  );
}
