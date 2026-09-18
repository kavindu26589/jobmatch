import { useState } from "react";
import { api } from "../api";
import { useCv } from "../cv";
import type {
  JobMatch,
  ResumeImprovementReport,
  ResumeProfile,
  TranscriptMessage,
  UsageRecord,
} from "../types";
import { EmptyState, ErrorBox, Panel, SkeletonLines, UsageLine, Warnings } from "../ui";
import ImprovementReport from "./ImprovementReport";
import JobCard from "./JobCard";
import ProfileCard from "./ProfileCard";
import { toast } from "./Toast";

export default function AgentTab({ onGoToCv }: { onGoToCv: () => void }) {
  const cv = useCv();
  const [question, setQuestion] = useState(
    "Analyze my resume, find the best-matching live jobs, score them, and produce a resume improvement plan.",
  );
  const [query, setQuery] = useState("");
  const [location, setLocation] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<TranscriptMessage[]>([]);
  const [matches, setMatches] = useState<JobMatch[]>([]);
  const [profile, setProfile] = useState<ResumeProfile | null>(null);
  const [improvement, setImprovement] = useState<ResumeImprovementReport | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [usage, setUsage] = useState<UsageRecord[]>([]);
  const [cost, setCost] = useState<number | undefined>(undefined);

  const run = async () => {
    if (!cv.text.trim() || running) return;
    setRunning(true);
    setError(null);
    setTranscript([]);
    setMatches([]);
    setProfile(null);
    setImprovement(null);
    setWarnings([]);
    try {
      const result = await api.agent({
        resume_text: cv.text,
        query,
        location,
        question,
        limit: 50,
        llm_top_n: 10,
        min_score: 0,
        improve: false,
      });
      setTranscript(result.agent_transcript ?? []);
      setMatches(result.matches ?? []);
      setProfile(result.profile ?? null);
      setImprovement(result.improvement ?? null);
      setWarnings(result.warnings ?? []);
      setUsage(result.usage ?? []);
      setCost(result.total_cost_usd);
      toast("Agent finished — review the trace and results", "ok");
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
          title="The agent needs your CV"
          hint="This tab lets an autonomous agent plan, search live jobs, score your fit, and draft an improvement plan."
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
      <div className="textarea-row">
        <label>Goal for the autonomous agent</label>
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="What should the agent do with your CV?"
        />
      </div>
      <div className="grid2">
        <label>
          Seed keywords <span className="caption">(optional)</span>
          <input value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <label>
          Location <span className="caption">(optional)</span>
          <input value={location} onChange={(e) => setLocation(e.target.value)} />
        </label>
      </div>
      <div className="toolbar">
        <button className="btn primary" onClick={run} disabled={running}>
          {running ? "Agent running…" : "Run agent"}
        </button>
      </div>

      {running && (
        <div className="thinking-row">
          <span className="pulse" />
          <span className="pulse" />
          <span className="pulse" />
          <span className="caption">the agent is planning, searching and scoring…</span>
        </div>
      )}
      <ErrorBox error={error} />
      <Warnings warnings={warnings} />

      {running && matches.length === 0 && transcript.length === 0 && <SkeletonLines lines={5} />}

      {transcript.length > 0 && (
        <div className="seg">
          <h4>Agent trace</h4>
          {transcript.map((m, i) => {
            const who = m.role === "user" ? "You" : m.name ? `Agent · ${m.name}` : "Agent";
            return (
              <div key={i} className={`trace ${m.role === "user" ? "trace-user" : "trace-agent"}`}>
                <b>{who}</b>
                {m.final ? <span className="chip chip-ok">final</span> : null}
                <p>{m.content}</p>
              </div>
            );
          })}
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
      {improvement && <ImprovementReport report={improvement} />}
      {profile && <ProfileCard profile={profile} />}
      <UsageLine usage={usage} cost={cost} />
    </Panel>
  );
}