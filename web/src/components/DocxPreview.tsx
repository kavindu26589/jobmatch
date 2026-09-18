import { useEffect, useRef, useState } from "react";
import { renderAsync } from "docx-preview";
import { getApiKey } from "../api";

export default function DocxPreview({ url }: { url: string }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setReady(false);
    setError(null);
    const load = async () => {
      const headers = new Headers();
      const key = getApiKey();
      if (key) headers.set("Authorization", `Bearer ${key}`);
      const resp = await fetch(url, { headers });
      if (!resp.ok) throw new Error(`HTTP ${resp.status} while loading the DOCX`);
      if (!hostRef.current) return;
      hostRef.current.innerHTML = "";
      await renderAsync(await resp.blob(), hostRef.current);
      if (!cancelled) setReady(true);
    };
    load().catch((err) => {
      if (!cancelled) setError(err instanceof Error ? err.message : String(err));
    });
    return () => {
      cancelled = true;
    };
  }, [url]);

  if (error) {
    return (
      <div className="preview-error">
        <p>Could not render the DOCX preview.</p>
        <p className="caption">{error}</p>
      </div>
    );
  }

  return (
    <>
      {!ready && <div className="preview-loading">Rendering DOCX…</div>}
      <div className="docx-preview" ref={hostRef} />
    </>
  );
}