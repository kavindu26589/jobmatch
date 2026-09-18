import { useEffect, useMemo, useRef, type ReactNode } from "react";
import { findSpan, useCv, type EditRecord, type Span } from "../cv";

export interface ActiveHint {
  original: string;
  rewritten: string;
}

interface MarkDef {
  id: string;
  cls: string;
  span: Span;
  active: boolean;
}

function buildMarks(text: string, active: ActiveHint | null, edits: EditRecord[]): MarkDef[] {
  const marks: MarkDef[] = [];
  if (active && active.original.trim() && active.original !== active.rewritten) {
    const span = findSpan(text, active.original);
    if (span) marks.push({ id: "active", cls: "pv-active", span, active: true });
  }
  for (const edit of edits) {
    if (!edit.applied || !edit.rewritten.trim()) continue;
    const span = findSpan(text, edit.rewritten);
    if (span && span.end - span.start < 600) {
      marks.push({ id: edit.id, cls: "pv-applied", span, active: false });
    }
  }
  marks.sort((a, b) => a.span.start - b.span.start);
  const clean: MarkDef[] = [];
  for (const mark of marks) {
    const overlaps = clean.some((c) => mark.span.start < c.span.end && c.span.start < mark.span.end);
    if (!overlaps) clean.push(mark);
  }
  return clean;
}

function renderMarked(text: string, marks: MarkDef[]): ReactNode[] {
  const out: ReactNode[] = [];
  let cursor = 0;
  for (const mark of marks) {
    if (mark.span.start < cursor || mark.span.start > text.length) continue;
    if (mark.span.start > cursor) out.push(text.slice(cursor, mark.span.start));
    out.push(
      <mark
        key={mark.id}
        className={mark.cls}
        data-marker={mark.active ? "active" : undefined}
      >
        {text.slice(mark.span.start, mark.span.end)}
      </mark>,
    );
    cursor = mark.span.end;
  }
  if (cursor < text.length) out.push(text.slice(cursor));
  return out;
}

export default function PreviewPane({ active }: { active: ActiveHint | null }) {
  const { text, edits } = useCv();
  const ref = useRef<HTMLDivElement>(null);

  const marks = useMemo(() => buildMarks(text, active, edits), [text, active, edits]);
  const nodes = useMemo(() => renderMarked(text, marks), [text, marks]);

  useEffect(() => {
    if (!active) return;
    const el = ref.current?.querySelector("[data-marker=active]");
    el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [active]);

  return (
    <div className="preview-pane" ref={ref} aria-label="CV preview with highlighted changes">
      {text ? (
        nodes
      ) : (
        <p className="empty">
          Load a CV to preview it here. Accepted edits and the suggestion you are inspecting are
          highlighted inline.
        </p>
      )}
    </div>
  );
}