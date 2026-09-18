import { useState } from "react";
import { api } from "../api";
import { useCv } from "../cv";
import type { JobMatch, ResumeProfile, UsageRecord } from "../types";
import { EmptyState, ErrorBox, Panel, SkeletonLines, UsageLine, Warnings } from "../ui";
import JobCard from "./JobCard";
import PipelineSteps from "./PipelineSteps";
import { toast } from "./Toast";

interface Controls {
  query: string;
  location: string;
  remoteOnly: boolean;
  llmTopN: number;
  minScore: number;
}

export default function JobsTab({ onGoToCv }: { onGoToCv: () => void }) {
  const cv = useCv();
  const [controls, setControls] = useState<Controls>({
    query: "python backend",
    location: "",
    remoteOnly: false,
    llmTopN: 15,
    minScore: 20,
  });
  const [running, setRunning] = useState(false);
  const [finished, setFinished] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [matches, setMatches] = useState<JobMatch[]>([]);
  const [profile, setProfile] = useState<ResumeProfile | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [usage, setUsage] = useState<UsageRecord[]>([]);
  const [cost, setCost] = useState<number | undefined>(undefined);
  const [lastQuery, setLastQuery] = useState("");

  const set = <K extends keyof Controls>(key: K, value: Controls[K]) =>
    setControls((prev) => ({ ...prev, [key]: value }));

  const run = async () => {
    if (!cv.text.trim() || running) return;
    setRunning(true);
    setFinished(false);
    setError(null);
    try {
      const result = await api.match({
        resume_text: cv.text,
        query: controls.query,
        location: controls.location,
        remote_only: controls.remoteOnly,
        limit: 50,
        llm_top_n: controls.llmTopN,
        min_score: controls.minScore,
        improve: false,
      });
      setMatches(result.matches ?? []);
      setProfile(result.profile ?? null);
      setWarnings(result.warnings ?? []);
      setUsage(result.usage ?? []);
      setCost(result.total_cost_usd);
      setLastQuery(controls.query || "all roles");
      setFinished(true);
      toast(
        `${result.matches?.length ?? 0} job${(result.matches?.length ?? 0) === 1 ? "" : "s"} suggested — open a job to see how to match it`,
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
          title="Add a CV to get job suggestions"
          hint="This tab scans live job boards, scores each opening against your CV, and shows exactly which parts to update to best match each job."
        >
          <button className="btn primary" onClick={onGoToCv}>
            Go to CV tab
          </button>
        </EmptyState>
      </Panel>
    );
  }

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
            LLM top-N <span className="caption">(jobs with tailored fit feedback)</span>
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
          {running ? "Searching jobs…" : "Suggest jobs for my CV"}
        </button>
        <span className="caption">{lastQuery && `matching against: ${lastQuery}`}</span>
      </div>

      {(running || finished) && <PipelineSteps running={running} done={!running && finished} />}
      <ErrorBox error={error} />
      <Warnings warnings={warnings} />

      {running ? (
        <Panel>
          <SkeletonLines lines={7} />
        </Panel>
      ) : matches.length > 0 ? (
        <div className="results">
          {profile && (
            <div className="seg">
              <h4>Profile seen by the scorer</h4>
              <div className="caption">
                {profile.contact.name || "—"} · {profile.contact.email || "—"} ·{" "}
                {profile.contact.location || "—"}
              </div>
              <div className="skills">
                {profile.hard_skills.map((s) => (
                  <span key={s} className="chip chip-ok">
                    {s}
                  </span>
                ))}
              </div>
            </div>
          )}
          <div className="seg">
            <h4>
              Suggested jobs <span className="caption">(ranked by fit to your CV)</span>
            </h4>
            <div className="job-list">
              {matches.map((m) => (
                <JobCard key={m.listing.external_id + m.listing.source} match={m} />
              ))}
            </div>
          </div>
          <UsageLine usage={usage} cost={cost} />
        </div>
      ) : (
        !running &&
        !error && (
          <EmptyState
            title="Ready when you are"
            hint="Click 'Suggest jobs for my CV' to search live job boards and score them against your resume."
          />
        )
      )}
    </Panel>
  );
}