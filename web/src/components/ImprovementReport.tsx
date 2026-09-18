import { useState } from "react";
import { useCv } from "../cv";
import type { ResumeImprovementReport, RewriteSuggestion } from "../types";
import { toast } from "./Toast";
import DiffView from "./Diff";

interface Keyable {
  section: string;
  original: string;
  rewritten: string;
}

function keyOf(s: Keyable): string {
  return `${s.section}\u0000${s.original}\u0000${s.rewritten}`;
}

function PriorityBadge({ priority }: { priority: string }) {
  return <span className={`prio prio-${priority || "P3"}`}>{priority || "–"}</span>;
}

export default function ImprovementReport({
  report,
  onShowInCv,
}: {
  report: ResumeImprovementReport;
  onShowInCv?: (suggestion: RewriteSuggestion) => void;
}) {
  const cv = useCv();
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const appliedKeys = new Set(
    cv.edits.filter((e) => e.applied).map((e) => `${e.section}\u0000${e.original}\u0000${e.rewritten}`),
  );

  const copyText = async (key: string, content: string) => {
    try {
      await navigator.clipboard.writeText(content);
      toast("Copied to clipboard", "ok");
    } catch {
      toast("Couldn't copy — clipboard unavailable", "err");
    }
    setCopiedKey(key);
    window.setTimeout(() => setCopiedKey((current) => (current === key ? null : current)), 1600);
  };

  const allSuggestions = report.sections.flatMap((s) => s.suggestions);

  return (
    <div className="improvement">
      <div className="ats-row">
        <div className="ats-score">
          <span>{report.overall_ats_score != null ? Math.round(report.overall_ats_score) : "–"}</span>
          <label>ATS score</label>
        </div>
        <div className="grow">
          <h3>Improvement plan</h3>
          {report.summary && <p className="caption">{report.summary}</p>}
          {report.target_titles.length > 0 && (
            <p className="caption">
              targeting: <b>{report.target_titles.join(" · ")}</b>
            </p>
          )}
        </div>
        {allSuggestions.length > 0 && (
          <button
            className="btn"
            onClick={() => {
              const records = cv.applyEdits(allSuggestions);
              const appliedCount = records.filter((r) => r.applied).length;
              toast(
                appliedCount === records.length
                  ? `Applied ${appliedCount} edit${appliedCount === 1 ? "" : "s"}`
                  : `Applied ${appliedCount}/${records.length} — the rest need manual fixes`,
                appliedCount === records.length ? "ok" : "err",
              );
            }}
            title="Apply every rewrite that maps to the CV text"
          >
            Accept all ({allSuggestions.length})
          </button>
        )}
      </div>

      {report.missing_keywords.length > 0 && (
        <div className="seg">
          <h4>Missing keywords</h4>
          <div className="skills">
            {report.missing_keywords.map((k) => (
              <span key={k.keyword} className="chip chip-warn" title={`in ${k.appears_in_targets} target(s)`}>
                {k.keyword}
              </span>
            ))}
          </div>
        </div>
      )}

      {report.sections.map((section) => (
        <div key={section.section} className="seg">
          <h4>{section.section || "section"}</h4>
          {section.strengths.length > 0 && (
            <ul className="good">
              {section.strengths.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ul>
          )}
          {section.issues.length > 0 && (
            <ul className="bad">
              {section.issues.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ul>
          )}
          {section.suggestions.map((s) => {
            const applied = appliedKeys.has(keyOf(s));
            const noSource = !s.original.trim();
            const showable = !noSource && !applied && onShowInCv && cv.canApply(s.original) !== "none";
            return (
              <div key={keyOf(s)} className={`rewrite ${applied ? "applied" : ""}`}>
                <div className="rewrite-head">
                  <PriorityBadge priority={s.priority} />
                  <span className="grow" />
                  {showable && (
                    <button
                      className="btn tiny"
                      title="Highlight this passage in the CV preview"
                      onClick={() => onShowInCv?.(s)}
                    >
                      Show in CV
                    </button>
                  )}
                  {applied ? (
                    <button
                      className="btn tiny"
                      title="Revert this edit"
                      onClick={() => {
                        const record = cv.edits.find((e) => e.applied && keyOf(e) === keyOf(s));
                        if (record) {
                          cv.undoEdit(record.id);
                          toast("Edit reverted", "ok");
                        }
                      }}
                    >
                      Undo
                    </button>
                  ) : noSource ? (
                    <button className="btn tiny" onClick={() => void copyText(keyOf(s), s.rewritten)}>
                      {copiedKey === keyOf(s) ? "Copied" : "Copy new text"}
                    </button>
                  ) : (
                    <button
                      className="btn primary tiny"
                      onClick={() => {
                        const records = cv.applyEdits([s]);
                        const applied = records[0]?.applied ?? false;
                        toast(
                          applied ? "Edit applied to your CV" : "Couldn't locate that text automatically",
                          applied ? "ok" : "err",
                        );
                      }}
                      disabled={applied}
                    >
                      {applied ? "Applied" : "Accept edit"}
                    </button>
                  )}
                </div>
                {noSource && !applied && <p className="caption">(no exact source text supplied)</p>}
                {s.original && (
                  <p className="diff-wrap">
                    <DiffView before={s.original} after={s.rewritten} />
                  </p>
                )}
                {s.rationale && <p className="why">{s.rationale}</p>}
              </div>
            );
          })}
        </div>
      ))}

      {report.priority_actions.length > 0 && (
        <div className="seg">
          <h4>Priority actions</h4>
          <ol className="actions">
            {report.priority_actions.map((a, i) => (
              <li key={i}>
                <PriorityBadge priority={a.priority} /> {a.action}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}