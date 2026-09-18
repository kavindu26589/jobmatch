import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type DragEvent,
} from "react";
import { api, uploadFile } from "../api";
import { findSpan, useCv } from "../cv";
import type { PdfPositionsResult, PdfWordBox, ResumeProfile, UsageRecord } from "../types";
import { charCount, SAMPLE_RESUME, wordCount } from "../sample";
import { EmptyState, ErrorBox, Panel, Spinner, UsageLine } from "../ui";
import DownloadCV from "./DownloadCV";
import ProfileCard from "./ProfileCard";
import ResumePreview from "./ResumePreview";
import { toast } from "./Toast";

export default function ResumeTab() {
  const cv = useCv();
  const [busy, setBusy] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [profile, setProfile] = useState<ResumeProfile | null>(null);
  const [usage, setUsage] = useState<UsageRecord[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [positions, setPositions] = useState<PdfPositionsResult | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const textAreaRef = useRef<HTMLTextAreaElement>(null);
  const previewable = cv.upload?.extension === "pdf" || cv.upload?.extension === "docx";

  useEffect(() => {
    setPositions(null);
    if (cv.upload?.extension !== "pdf") return;
    let active = true;
    api
      .getPositions(cv.upload.upload_id)
      .then((result) => {
        if (active) setPositions(result);
      })
      .catch(() => {
        /* preview degrades to PDF only — editing still works via the text area */
      });
    return () => {
      active = false;
    };
  }, [cv.upload?.upload_id, cv.upload?.extension]);

  const jumpToWord = useCallback(
    (word: PdfWordBox) => {
      const textArea = textAreaRef.current;
      if (!textArea) return;
      const span = findSpan(cv.text, word.text);
      if (!span) {
        textArea.focus();
        toast(`Couldn't locate “${word.text}” in the text area`, "err");
        return;
      }
      textArea.focus();
      textArea.setSelectionRange(span.start, span.end);
      textArea.scrollIntoView({ block: "center", behavior: "smooth" });
    },
    [cv.text],
  );

  const handleFile = useCallback(
    async (file: File) => {
      setBusy(true);
      setError(null);
      setProfile(null);
      try {
        const result = await uploadFile(file);
        if (!cv.upload || result.upload_id !== cv.upload.upload_id) {
          cv.setUpload(result);
        }
        cv.setText(result.text);
        toast(`Loaded ${result.filename} (${wordCount(result.text)} words)`, "ok");
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        toast(err instanceof Error ? err.message : String(err), "err");
      } finally {
        setBusy(false);
      }
    },
    [cv],
  );

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) void handleFile(file);
  };

  const analyze = async () => {
    if (!cv.text.trim()) return;
    setAnalyzing(true);
    setError(null);
    try {
      const r = await api.analyze(cv.text.trim());
      setProfile(r.profile);
      setUsage(r.usage ?? []);
      toast("Profile parsed — review and edit the details below", "ok");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      toast(err instanceof Error ? err.message : String(err), "err");
    } finally {
      setAnalyzing(false);
    }
  };

  if (!cv.text.trim()) {
    return (
      <Panel>
        <EmptyState
          title="Start with your CV"
          hint="Upload a file (PDF, DOCX, TXT, MD, RTF — max 5 MB) or load a sample. We keep the original file so you can download your edits in the same format."
        >
          <button className="btn primary" onClick={() => inputRef.current?.click()}>
            Upload CV
          </button>
          <button
            className="btn soft"
            onClick={() => {
              if (!cv.text) {
                cv.setText(SAMPLE_RESUME);
                toast("Sample CV loaded — upload a file to enable export", "ok");
              }
            }}
          >
            Load sample CV
          </button>
          <input
            ref={inputRef}
            type="file"
            accept=".pdf,.docx,.txt,.md,.rtf"
            hidden
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void handleFile(file);
              e.target.value = "";
            }}
          />
        </EmptyState>
        <ErrorBox error={error} />
      </Panel>
    );
  }

  return (
    <Panel>
      {cv.restored && (
        <div className="restore">
          <span>Restored your previous session from this browser.</span>
          <button className="btn tiny" onClick={cv.dismissRestore}>
            Dismiss
          </button>
          <button className="btn tiny"
            onClick={() => {
              if (window.confirm("Clear the CV text and uploaded file?")) cv.reset();
            }}
          >
            Start over
          </button>
        </div>
      )}

      <div
        className={`dropzone ${dragOver ? "over" : ""} has`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        onClick={() => !busy && inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.docx,.txt,.md,.rtf"
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void handleFile(file);
            e.target.value = "";
          }}
        />
        {busy ? (
          <Spinner label="Uploading + extracting…" />
        ) : (
          <>
            <div className="file-name">✓ {cv.upload?.filename ?? "pasted text (no file)"}</div>
            <div className="caption">
              {cv.upload
                ? "drop a new file to replace · text below is editable"
                : "drop a file here to enable export in the original format"}
            </div>
          </>
        )}
      </div>

      <ErrorBox error={error} />

      <div className="toolbar">
        {cv.upload && (
          <span className="caption">
            cached as <b>{cv.upload.extension.toUpperCase()}</b> · downloads keep that format
          </span>
        )}
        <span className="caption">
          {wordCount(cv.text)} words · {charCount(cv.text)} chars
        </span>
        <span className="grow" />
        <button
          className="btn soft"
          onClick={() => {
            if (window.confirm("Clear the CV text and uploaded file?")) cv.reset();
          }}
        >
          Reset
        </button>
        <DownloadCV compact />
      </div>

      <div className={`textarea-row ${previewable ? "split" : ""}`}>
        {previewable && cv.upload && (
          <div className="resume-preview">
            <div className="preview-caption">
              Original <b>{cv.upload.extension.toUpperCase()}</b> (click a word to jump to it in
              the text area)
            </div>
            <ResumePreview
              upload={cv.upload}
              positions={positions ? positions.pages : null}
              onSelectWord={jumpToWord}
            />
          </div>
        )}
        <div className="resume-edit">
          <label>
            CV text{" "}
            <span className="caption">
              (the source the agent works on — edits are written back into the{" "}
              {previewable ? "original design" : "original format"} on download)
            </span>
          </label>
          <textarea
            ref={textAreaRef}
            value={cv.text}
            spellCheck={false}
            rows={14}
            placeholder="Paste resume text or upload a file…"
            onChange={(e) => cv.setText(e.target.value)}
          />
        </div>
      </div>

      <div className="toolbar">
        <button className="btn primary" onClick={analyze} disabled={analyzing || !cv.text.trim()}>
          {analyzing ? "Analyzing…" : "Analyze profile"}
        </button>
      </div>
      <UsageLine usage={usage} />

      {cv.edits.length > 0 && (
        <div className="seg">
          <h4>
            Applied edits ({cv.edits.length})
            <span className="caption"> · Ctrl/Cmd+Z undoes the last one</span>
          </h4>
          {cv.edits.map((e) => (
            <div key={e.id} className={`rewrite ${e.applied ? "applied" : ""}`}>
              <div className="rewrite-head">
                <span className="caption">{e.section}</span>
                <span className="grow" />
                {e.applied && (
                  <button
                    className="btn tiny"
                    onClick={() => {
                      cv.undoEdit(e.id);
                      toast("Edit reverted", "ok");
                    }}
                  >
                    Undo
                  </button>
                )}
              </div>
              {e.applied ? (
                <p className="caption">
                  <b>now:</b> {e.rewritten}
                </p>
              ) : (
                <p className="caption">{e.note ?? "not applied"}</p>
              )}
            </div>
          ))}
        </div>
      )}

      {profile && <ProfileCard profile={profile} editable />}
    </Panel>
  );
}