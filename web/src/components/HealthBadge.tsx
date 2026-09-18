import { useEffect, useState } from "react";
import { health } from "../api";
import type { HealthStatus } from "../types";

export default function HealthBadge() {
  const [status, setStatus] = useState<HealthStatus | null>(null);
  const [down, setDown] = useState(false);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const got = await health();
        if (!alive) return;
        setStatus(got);
        setDown(false);
      } catch {
        if (alive) setDown(true);
      }
    };
    void tick();
    const id = setInterval(tick, 30000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  if (down) return <span className="badge badge-err">server offline</span>;
  if (!status) return <span className="badge badge-muted">checking…</span>;
  return (
    <span
      className="badge badge-ok"
      title={
        `model: ${status.model ?? "?"} · ` +
        `limit: $${status.cost_limit_usd ?? "?"}/mo · ` +
        `sources: ${(status.sources ?? []).join(", ")}`
      }
    >
      gateway · {status.provider ?? "?"}
    </span>
  );
}