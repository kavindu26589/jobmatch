import { useState } from "react";
import { useCv } from "../cv";
import type { JobMatch } from "../types";
import DiffView from "./Diff";
import { toast } from "./Toast";

function FitRing({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(100, Math.round(score)));
  const r = 15.5;
  const circumference = 2 * Math.PI * r;
  const offset = circumference * (1 - pct / 100);
  const color = pct >= 70 ? "var(--green)" : pct >= 45 ? "var(--amber)" : "var(--muted)";
  return (
    <svg className="fit-ring" width="42" height="42" viewBox="0 0 42 42" aria-label={`fit score ${pct}%`}>
      <circle cx="21" cy="21" r={r} fill="none" stroke="var(--border)" strokeWidth="4" />
      <circle
        cx="21"
        cy="21"
        r={r}
        fill="none"
        stroke={color}
        strokeWidth="4"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        transform="rotate(-90 21 21)"
      />
      <text x="21" y="21" className="fit-ring-text" textAnchor="middle" dominantBaseline="central">
        {pct}
      </text>
    </svg>
  );
}

function keyOf(action: { area: string; original: string; rewritten: string }): string {
  return `${action.area}\u0000${action.original}\u0000${action.rewritten}`;
}

export default function JobCard({ match }: { match: JobMatch }) {
  const { listing, score } = match;
  const cv = useCv();
  const [open, setOpen] = useState(false);
  const sourceClass = `chip chip-source chip-source-${listing.source.toLowerCase().replace(/[^a-z0-9]+/g, "")}`;
  const improvement = score.improvement ?? null;
  const actionable = improvement?.actions.filter((a) => a.original && a.rewritten) ?? [];
  const appliedKeys = new Set(
    cv.edits.filter((e) => e.applied).map((e) => `${e.section}\u0000${e.original}\u0000${e.rewritten}`),
  );

  return (
    <article className="job-card">
      <div className="job-card-head">
        <FitRing score={score.fit_score} />
        <div className="job-card-main">
          <div className="job-card-title-row">
            <span className={sourceClass}>{listing.source}</span>
            <h4 className="job-card-title">{listing.title}</h4>
            {match.rank != null && <span className="job-rank">#{match.rank + 1}</span>}
          </div>
          <div className="job-card-meta">
            <span>{listing.company}</span>
            <span aria-hidden="true">·</span>
            <span>{listing.location || "Remote / unspecified"}</span>
            {listing.salary && (
              <>
                <span aria-hidden="true">·</span>
                <span className="job-salary">{listing.salary}</span>
              </>
            )}
            {listing.employment_type && (
              <>
                <span aria-hidden="true">·</span>
                <span>{listing.employment_type}</span>
              </>
            )}
          </div>
        </div>
        <div className="job-card-actions">
          {score.overqualified && <span className="chip chip-warn">overqualified</span>}
          {listing.url ? (
            <a
              className="btn soft"
              href={listing.url}
              target="_blank"
              rel="noreferrer noopener"
              title="Open original listing"
            >
              Apply ↗
            </a>
          ) : (
            <span className="chip">no link</span>
          )}
          <button type="button" className="btn text" onClick={() => setOpen((o) => !o)}>
            {open ? "Less" : improvement ? "How to match" : "Why this fit"}
          </button>
        </div>
      </div>
      {open && (
        <div className="job-card-detail">
          {score.reasoning && (
            <p className="job-reasoning">
              <strong>Why:</strong> {score.reasoning}
            </p>
          )}
          {(score.matched_skills.length > 0 || score.missing_skills.length > 0) && (
            <div className="skill-chips">
              {score.matched_skills.map((s) => (
                <span key={`m-${s}`} className="chip chip-ok">
                  {s}
                </span>
              ))}
              {score.missing_skills.map((s) => (
                <span key={`x-${s}`} className="chip chip-warn">
                  ✕ {s}
                </span>
              ))}
            </div>
          )}

          {improvement && (
            <div className="job-improve">
              {improvement.summary && <p className="job-improve-summary">{improvement.summary}</p>}
              {improvement.actions.length > 0 && (
                <ol className="job-improve-list">
                  {improvement.actions.map((action, i) => {
                    const key = keyOf(action);
                    const applied = appliedKeys.has(key);
                    const hasRewrite = Boolean(action.original && action.rewritten);
                    return (
                      <li key={`${key}-${i}`} className={`job-improve-item ${applied ? "applied" : ""}`}>
                        <div className="job-improve-item-head">
                          <span className="chip chip-source">{action.area || "cv"}</span>
                          <span className="grow" />
                          <span className={`prio prio-${action.priority || "P1"}`}>
                            {action.priority || "P1"}
                          </span>
                        </div>
                        <p className="caption">{action.advice}</p>
                        {hasRewrite && (
                          <div className="job-improve-edit">
                            <div className="diff-wrap">
                              <DiffView before={action.original} after={action.rewritten} />
                            </div>
                            <div className="job-improve-actions">
                              {applied ? (
                                <button
                                  type="button"
                                  className="btn tiny"
                                  onClick={() => {
                                    const record = cv.edits.find(
                                      (e) =>
                                        e.applied &&
                                        `${e.section}\u0000${e.original}\u0000${e.rewritten}` === key,
                                    );
                                    if (record) {
                                      cv.undoEdit(record.id);
                                      toast("Edit reverted", "ok");
                                    }
                                  }}
                                >
                                  Undo
                                </button>
                              ) : (
                                <button
                                  type="button"
                                  className="btn primary tiny"
                                  onClick={() => {
                                    const records = cv.applyEdits([
                                      {
                                        section: action.area || "skills",
                                        original: action.original,
                                        rewritten: action.rewritten,
                                        rationale: action.advice,
                                        priority: action.priority,
                                      },
                                    ]);
                                    toast(
                                      records[0]?.applied
                                        ? "Edit applied to your CV"
                                        : "Couldn't locate that text automatically",
                                      records[0]?.applied ? "ok" : "err",
                                    );
                                  }}
                                >
                                  Accept edit
                                </button>
                              )}
                            </div>
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ol>
              )}
              {actionable.length === 0 && (
                <p className="caption">No ready-to-apply rewrites — review the advice above.</p>
              )}
            </div>
          )}
        </div>
      )}
    </article>
  );
}