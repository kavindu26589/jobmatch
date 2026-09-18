import type { ReactNode } from "react";
import type { UsageRecord } from "./types";

export function UsageLine({ usage, cost }: { usage?: UsageRecord[]; cost?: number }) {
  if ((!usage || usage.length === 0) && cost == null) return null;
  return (
    <div className="usage caption">
      {usage?.map((u, i) => (
        <span key={i}>
          {u.model ?? "llm"}
          {u.kind ? ` · ${u.kind}` : ""}
          {u.input_tokens != null ? ` · ${u.input_tokens}/${u.output_tokens ?? 0} tok` : ""}
          {"  "}
        </span>
      ))}
      {cost != null && <span>
        total: <b>${Number(cost).toFixed(4)}</b>
      </span>}
    </div>
  );
}

export function Warnings({ warnings }: { warnings: string[] }) {
  if (!warnings || warnings.length === 0) return null;
  return (
    <div className="warnings">
      {warnings.map((w, i) => (
        <div key={i} className="warn">
          {w}
        </div>
      ))}
    </div>
  );
}

export function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null;
  return <div className="error">{error}</div>;
}

export function Spinner({ label }: { label: string }) {
  return (
    <span className="loading-row">
      <span className="spinner" /> {label}
    </span>
  );
}

export function SkeletonLines({ lines = 4 }: { lines?: number }) {
  return (
    <div className="skeleton" aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <div
          key={i}
          className="skeleton-line"
          style={i % 3 === 2 ? { width: "62%" } : undefined}
        />
      ))}
    </div>
  );
}

export function Panel({ children }: { children: ReactNode }) {
  return <section className="panel-card">{children}</section>;
}

export function EmptyState({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon" aria-hidden="true">
        ◧
      </div>
      <h3>{title}</h3>
      {hint && <p className="caption">{hint}</p>}
      {children && <div className="empty-actions">{children}</div>}
    </div>
  );
}