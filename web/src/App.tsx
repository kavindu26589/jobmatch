import { useEffect, useState } from "react";
import { getApiKey, setApiKey } from "./api";
import { CvProvider, useCv } from "./cv";
import AgentTab from "./components/AgentTab";
import HealthBadge from "./components/HealthBadge";
import ImproveTab from "./components/ImproveTab";
import JobsTab from "./components/JobsTab";
import ResumeTab from "./components/ResumeTab";
import ThemeToggle from "./components/ThemeToggle";
import ToastHost from "./components/Toast";
import WorkflowBanner from "./components/WorkflowBanner";

type Tab = "resume" | "jobs" | "improve" | "agent";

const TABS: { id: Tab; label: string }[] = [
  { id: "resume", label: "CV" },
  { id: "jobs", label: "Jobs" },
  { id: "improve", label: "Improve" },
  { id: "agent", label: "Agent" },
];

function Shell() {
  const [tab, setTab] = useState<Tab>("resume");
  const [key, setKey] = useState(getApiKey());
  const { undo } = useCv();

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "z") return;
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "TEXTAREA" || target.tagName === "INPUT")) return;
      e.preventDefault();
      undo();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [undo]);

  const goToCv = () => setTab("resume");

  return (
    <div className="app">
      <header>
        <div className="brand">
          <span className="logo" aria-hidden="true">
            ◧
          </span>
          <div>
            <h1>jobmatcher</h1>
            <p className="tagline">upload a CV · the agent optimizes it · download the edited file</p>
          </div>
        </div>
        <div className="header-right">
          <HealthBadge />
          <ThemeToggle />
          <label className="apikey">
            API key
            <input
              type="password"
              value={key}
              placeholder="optional"
              autoComplete="off"
              onChange={(e) => {
                setKey(e.target.value);
                setApiKey(e.target.value);
              }}
            />
          </label>
        </div>
      </header>

      <WorkflowBanner />

      <nav>
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`tab ${tab === t.id ? "active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <main>
        {tab === "resume" && <ResumeTab />}
        {tab === "jobs" && <JobsTab key={tab} onGoToCv={goToCv} />}
        {tab === "improve" && <ImproveTab key={tab} onGoToCv={goToCv} />}
        {tab === "agent" && <AgentTab key={tab} onGoToCv={goToCv} />}
      </main>

      <footer>jobmatcher · self-hosted · LLM via opencode-gateway</footer>

      <ToastHost />
    </div>
  );
}

export default function App() {
  return (
    <CvProvider>
      <Shell />
    </CvProvider>
  );
}