import "./Note.css";

type NoteProps = {
  children: string;
};

/** The one message that stands in for a list: nothing stocked, nothing matched, nothing loaded. */
export function Note({ children }: NoteProps) {
  return (
    <p className="iq-note" role="status">
      {children}
    </p>
  );
}
