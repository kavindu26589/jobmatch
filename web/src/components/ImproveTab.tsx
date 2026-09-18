import { useState } from "react";
import { api } from "../api";
import { useCv } from "../cv";
import type { JobMatch, ResumeImprovementReport, ResumeProfile, UsageRecord } from "../types";
import { EmptyState, ErrorBox, Panel, SkeletonLines, UsageLine, Warnings } from "../ui";
import ImprovementReport from "./ImprovementReport";
import JobCard from "./JobCard";
import PipelineSteps from "./PipelineSteps";
import PreviewPane, { type ActiveHint } from "./PreviewPane";
import { toast } from "./Toast";

interface Controls {
  query: string;
  location: string;
  remoteOnly: boolean;
  llmTopN: number;
  minScore: number;
}

export default function ImproveTab({ onGoToCv }: { onGoToCv: () => void }) {
  const cv = useCv();
  const [controls, setControls] = useState<Controls>({
    query: "python backend",
    location: "",
    remoteOnly: false,
    llmTopN: 15,
    minScore: 30,
  });
  const [running, setRunning] = useState(false);
  const [finished, setFinished] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ResumeImprovementReport | null>(null);
  const [matches, setMatches] = useState<JobMatch[]>([]);
  const [profile, setProfile] = useState<ResumeProfile | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [usage, setUsage] = useState<UsageRecord[]>([]);
  const [cost, setCost] = useState<number | undefined>(undefined);
  const [lastQuery, setLastQuery] = useState("");
  const [active, setActive] = useState<ActiveHint | null>(null);

  const set = <K extends keyof Controls>(key: K, value: Controls[K]) =>
    setControls((prev) => ({ ...prev, [key]: value }));

  const run = async () => {
    if (!cv.text.trim()) return;
    if (running) return;
    setRunning(true);
    setFinished(false);
    setError(null);
    setActive(null);
    try {
      const result = await api.match({
        resume_text: cv.text,
        query: controls.query,
        location: controls.location,
        remote_only: controls.remoteOnly,
        limit: 50,
        llm_top_n: controls.llmTopN,
        min_score: controls.minScore,
        improve: true,
      });
      setReport(result.improvement ?? null);
      setMatches(result.matches ?? []);
      setProfile(result.profile ?? null);
      setWarnings(result.warnings ?? []);
      setUsage(result.usage ?? []);
      setCost(result.total_cost_usd);
      setLastQuery(controls.query || "all roles");
      setFinished(true);
      toast(
        `${result.matches?.length ?? 0} job${(result.matches?.length ?? 0) === 1 ? "" : "s"} matched — review edits below`,
        "ok",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      toast(err instanceof Error ? err.message : String(err), "err");
    } finally {
      setRunning(false);
    }
  };

  if (!cv.text.trim()) {
    return (
      <Panel>
        <EmptyState
          title="Add a CV before improving"
          hint="This tab runs the full pipeline: resume analysis → job search → fit scoring → ATS improvement plan."
        >
          <button className="btn primary" onClick={onGoToCv}>
            Go to CV tab
          </button>
        </EmptyState>
      </Panel>
    );
  }

  const hasResult = report || matches.length > 0;

  return (
    <Panel>
      <div className="grid3">
        <label>
          Target keywords
          <input
            value={controls.query}
            placeholder="e.g. python backend"
            onChange={(e) => set("query", e.target.value)}
          />
        </label>
        <label>
          Location
          <input
            value={controls.location}
            placeholder="Remote, London…"
            onChange={(e) => set("location", e.target.value)}
          />
        </label>
        <div className="field-pair">
          <label>
            LLM top-N <span className="caption">(job shortlist for scoring)</span>
            <input
              type="number"
              min={1}
              max={100}
              value={controls.llmTopN}
              onChange={(e) => set("llmTopN", Number(e.target.value) || 15)}
            />
          </label>
          <label>
            Min fit score
            <input
              type="number"
              min={0}
              max={100}
              value={controls.minScore}
              onChange={(e) => set("minScore", Number(e.target.value) || 0)}
            />
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={controls.remoteOnly}
              onChange={(e) => set("remoteOnly", e.target.checked)}
            />
            remote only
          </label>
        </div>
      </div>

      <div className="toolbar">
        <button className="btn primary" onClick={run} disabled={running}>
          {running ? "Running pipeline…" : "Analyze + search + score + improve"}
        </button>
        <span className="caption">{lastQuery && `optimizing for: ${lastQuery}`}</span>
      </div>

      {(running || finished) && <PipelineSteps running={running} done={!running && finished} />}
      <ErrorBox error={error} />
      <Warnings warnings={warnings} />

      <div className="improve-grid">
        <div className="improve-main">
          {running ? (
            <div className="seg">
              <h4>Pipeline</h4>
              <SkeletonLines lines={6} />
            </div>
          ) : hasResult ? (
            <div className="results">
              {profile && (
                <div className="seg">
                  <h4>Profile</h4>
                  <div className="caption">
                    {profile.contact.name || "—"} · {profile.contact.email || "—"} ·{" "}
                    {profile.contact.location || "—"}
                  </div>
                  <div className="skills">
                    {profile.hard_skills.map((s) => (
                      <span key={s} className="chip chip-green">
                        {s}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {matches.length > 0 && (
                <div className="seg">
                  <h4>Best-matching jobs</h4>
                  <div className="job-list">
                    {matches.map((m) => (
                      <JobCard key={m.listing.external_id + m.listing.source} match={m} />
                    ))}
                  </div>
                </div>
              )}

              {report && <ImprovementReport report={report} onShowInCv={(s) => setActive({ original: s.original, rewritten: s.rewritten })} />}

              <UsageLine usage={usage} cost={cost} />
            </div>
          ) : (
            <EmptyState
              title="Run the pipeline to get your improvement plan"
              hint="You'll get matched jobs, an ATS score, and word-level edit suggestions you can accept with one click."
            />
          )}
        </div>

        {!running && hasResult && (
          <aside className="improve-preview">
            <div className="preview-head">
              <h4>Live CV</h4>
              {active && (
                <button className="btn tiny" onClick={() => setActive(null)}>
                  Clear highlight
                </button>
              )}
            </div>
            <PreviewPane active={active} />
          </aside>
        )}
      </div>
    </Panel>
  );
}