import { toast } from "./Toast";
import DownloadCV from "./DownloadCV";
import { useCv } from "../cv";
import { wordCount } from "../sample";

interface StepDef {
  n: number;
  label: string;
  done: boolean;
  hint: string;
}

export function WorkflowBanner() {
  const { text, upload, edits } = useCv();
  const hasText = text.trim().length > 0;
  const steps: StepDef[] = [
    { n: 1, label: "Add your CV", done: hasText, hint: hasText ? "CV loaded" : "Upload or paste your CV on the CV tab" },
    { n: 2, label: "Get a fit report", done: edits.length > 0, hint: edits.length > 0 ? `${edits.length} edit(s) applied` : "Run Improve to score and edit your CV" },
    { n: 3, label: "Export", done: hasText && Boolean(upload), hint: upload ? "Ready to export in the original format" : "Upload your CV file to enable export" },
  ];

  const copyText = async () => {
    try {
      await navigator.clipboard.writeText(text);
      toast("CV text copied to clipboard", "ok");
    } catch {
      toast("Couldn't copy — clipboard unavailable", "err");
    }
  };

  return (
    <div className="workflow-banner">
      <ol className="workflow-steps">
        {steps.map((s) => (
          <li key={s.n} className={`wf-step ${s.done ? "wf-done" : ""}`} title={s.hint}>
            <span className="wf-dot">{s.done ? "✓" : s.n}</span>
            <span className="wf-label">{s.label}</span>
          </li>
        ))}
      </ol>
      <div className="workflow-actions">
        {text && (
          <span className="caption">
            {wordCount(text)} words · {edits.filter((e) => e.applied).length} applied
          </span>
        )}
        <button type="button" className="btn text" onClick={copyText} disabled={!hasText}>
          Copy text
        </button>
        <DownloadCV size="small" />
      </div>
    </div>
  );
}

export default WorkflowBanner;