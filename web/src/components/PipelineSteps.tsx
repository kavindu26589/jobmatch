const STEPS = ["Resume", "Search", "Score", "Improve"] as const;

export default function PipelineSteps({ running, done }: { running: boolean; done: boolean }) {
  return (
    <ol className="steps" aria-hidden="true">
      {STEPS.map((label, index) => (
        <li
          key={label}
          className={`step ${done ? "step-done" : running ? "step-run" : ""}`}
          style={running ? { animationDelay: `${index * 0.35}s` } : undefined}
        >
          <span className="step-dot">{done ? "✓" : index + 1}</span>
          {label}
        </li>
      ))}
    </ol>
  );
}