import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { RewriteSuggestion, UploadResult } from "./types";

export interface EditRecord {
  id: string;
  section: string;
  original: string;
  rewritten: string;
  applied: boolean;
  note?: string;
}

/** A located match inside some text. */
export interface Span {
  start: number;
  end: number;
}

export type ApplyResult = "exact" | "fuzzy" | "none" | "empty";

interface CvContextValue {
  text: string;
  setText: (t: string) => void;
  upload: UploadResult | null;
  setUpload: (u: UploadResult | null) => void;
  edits: EditRecord[];
  applyEdits: (suggestions: RewriteSuggestion[]) => EditRecord[];
  undoEdit: (id: string) => void;
  undo: () => void;
  clearEdits: () => void;
  reset: () => void;
  restored: boolean;
  dismissRestore: () => void;
  canApply: (original: string) => ApplyResult;
}

const CvContext = createContext<CvContextValue | null>(null);

const STORAGE_KEY = "jobmatcher.cv.v1";
const MAX_STORED_TEXT = 1_000_000;

interface Session {
  text: string;
  upload: UploadResult | null;
  edits: EditRecord[];
  savedAt: number;
}

function regExpEscape(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function fuzzySpan(text: string, original: string): Span | null {
  const pattern = original.split(/\s+/).map(regExpEscape).join("\\s+");
  const re = new RegExp(pattern, "iu");
  const m = re.exec(text);
  if (m) return { start: m.index, end: m.index + m[0].length };
  return null;
}

function matchSpan(text: string, original: string): Span | null {
  if (!text || !original.trim()) return null;
  const exact = text.indexOf(original);
  if (exact !== -1) return { start: exact, end: exact + original.length };
  return fuzzySpan(text, original);
}

/** Find the matched span of `original` inside `text` (exact, then fuzzy). */
export function findSpan(text: string, original: string): Span | null {
  return matchSpan(text, original);
}

/** Replace the first occurrence of `original` (exact, then whitespace/case-fuzzy). */
export function replaceOriginal(
  text: string,
  original: string,
  replacement: string,
): { next: string; applied: ApplyResult; span: Span | null } {
  if (!text || !original.trim()) return { next: text, applied: "empty", span: null };
  const exact = text.indexOf(original);
  if (exact !== -1) {
    const span: Span = { start: exact, end: exact + original.length };
    return {
      next: text.slice(0, exact) + replacement + text.slice(exact + original.length),
      applied: "exact",
      span,
    };
  }
  const span = fuzzySpan(text, original);
  if (!span) return { next: text, applied: "none", span: null };
  return {
    next: text.slice(0, span.start) + replacement + text.slice(span.end),
    applied: "fuzzy",
    span,
  };
}

function loadSession(): Session | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Session;
    if (typeof parsed.text !== "string" || !Array.isArray(parsed.edits)) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function CvProvider({ children }: { children: ReactNode }) {
  const [initial] = useState(loadSession);
  const [text, setText] = useState(initial?.text ?? "");
  const [upload, setUpload] = useState<UploadResult | null>(initial?.upload ?? null);
  const [edits, setEdits] = useState<EditRecord[]>(initial?.edits ?? []);
  const [restored, setRestored] = useState(Boolean(initial?.text));
  const textRef = useRef(text);
  useEffect(() => {
    textRef.current = text;
  }, [text]);

  /* Persistent session (debounced). */
  const saveTimer = useRef<number | undefined>(undefined);
  useEffect(() => {
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      try {
        if (!text && !upload) {
          localStorage.removeItem(STORAGE_KEY);
          return;
        }
        if (text.length > MAX_STORED_TEXT) return;
        const session: Session = {
          text,
          upload,
          edits: edits.slice(0, 50),
          savedAt: Date.now(),
        };
        localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
      } catch {
        /* storage full or unavailable — session simply won't persist */
      }
    }, 350);
    return () => window.clearTimeout(saveTimer.current);
  }, [text, upload, edits]);

  const applyEdits = useCallback(
    (suggestions: RewriteSuggestion[]): EditRecord[] => {
      const valid = suggestions.filter((s) => s.original.trim() && s.rewritten.trim());
      if (valid.length === 0) return [];
      const records: EditRecord[] = [];
      const next = valid.reduce(
        (acc, s, index) => {
          const res = replaceOriginal(acc.draft, s.original, s.rewritten);
          records.push({
            id: `e-${Date.now()}-${index}-${s.section.slice(0, 12)}`,
            section: s.section,
            original: s.original,
            rewritten: s.rewritten,
            applied: res.applied !== "none",
            note:
              res.applied === "none"
                ? "Couldn't locate this text in the CV automatically."
                : undefined,
          });
          return { draft: res.next };
        },
        { draft: text },
      );
      setText(next.draft);
      setEdits((prev) => [...records, ...prev]);
      return records;
    },
    [text],
  );

  const undoEdit = useCallback((id: string) => {
    setEdits((prev) => {
      const record = prev.find((e) => e.id === id);
      if (!record || !record.applied) return prev;
      const { next } = replaceOriginal(textRef.current, record.rewritten, record.original);
      setText(next);
      return prev.filter((e) => e.id !== id);
    });
  }, []);

  const undo = useCallback(() => {
    setEdits((prev) => {
      const latest = [...prev].find((e) => e.applied);
      if (!latest) return prev;
      const { next } = replaceOriginal(textRef.current, latest.rewritten, latest.original);
      setText(next);
      return prev.filter((e) => e.id !== latest.id);
    });
  }, []);

  const clearEdits = useCallback(() => setEdits([]), []);

  const dismissRestore = useCallback(() => setRestored(false), []);

  const reset = useCallback(() => {
    setText("");
    setUpload(null);
    setEdits([]);
    setRestored(false);
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
  }, []);

  const canApply = useCallback(
    (original: string) => replaceOriginal(text, original, "").applied,
    [text],
  );

  const value = useMemo<CvContextValue>(
    () => ({
      text,
      setText,
      upload,
      setUpload,
      edits,
      applyEdits,
      undoEdit,
      undo,
      clearEdits,
      reset,
      restored,
      dismissRestore,
      canApply,
    }),
    [text, setText, upload, setUpload, edits, applyEdits, undoEdit, undo, clearEdits, reset, restored, dismissRestore, canApply],
  );
  return <CvContext.Provider value={value}>{children}</CvContext.Provider>;
}

export function useCv(): CvContextValue {
  const ctx = useContext(CvContext);
  if (!ctx) throw new Error("useCv must be used inside CvProvider");
  return ctx;
}