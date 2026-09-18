import { useEffect, useState } from "react";

export type ToastKind = "ok" | "err" | "info";

export interface ToastItem {
  id: number;
  message: string;
  kind: ToastKind;
}

type Listener = (item: ToastItem) => void;

const listeners: Listener[] = [];
let seq = 0;

export function toast(message: string, kind: ToastKind = "info"): void {
  const item = { id: ++seq, message, kind };
  for (const listener of listeners) listener(item);
}

export default function ToastHost() {
  const [items, setItems] = useState<ToastItem[]>([]);

  useEffect(() => {
    const listener: Listener = (item) => {
      setItems((prev) => [...prev.slice(-3), item]);
      window.setTimeout(() => {
        setItems((prev) => prev.filter((t) => t.id !== item.id));
      }, 3800);
    };
    listeners.push(listener);
    return () => {
      const index = listeners.indexOf(listener);
      if (index !== -1) listeners.splice(index, 1);
    };
  }, []);

  return (
    <div className="toast-stack" aria-live="polite">
      {items.map((t) => (
        <div key={t.id} className={`toast toast-${t.kind}`}>
          <span className="toast-icon">{t.kind === "ok" ? "✓" : t.kind === "err" ? "✕" : "i"}</span>
          {t.message}
        </div>
      ))}
    </div>
  );
}