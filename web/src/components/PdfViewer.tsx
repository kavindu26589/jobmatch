import { useEffect, useRef, useState } from "react";
import * as pdfjsLib from "pdfjs-dist";
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { getApiKey } from "../api";
import type { PdfPageBoxes, PdfWordBox } from "../types";

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

interface PageMeta {
  num: number;
  width: number;
  height: number;
}

export default function PdfViewer({
  url,
  positions,
  scale = 1.4,
  onSelectWord,
}: {
  url: string;
  positions: PdfPageBoxes[] | null;
  scale?: number;
  onSelectWord?: (word: PdfWordBox) => void;
}) {
  const [pages, setPages] = useState<PageMeta[]>([]);
  const [error, setError] = useState<string | null>(null);
  const taskRef = useRef<pdfjsLib.PDFDocumentLoadingTask | null>(null);
  const docRef = useRef<pdfjsLib.PDFDocumentProxy | null>(null);
  const canvases = useRef(new Map<number, HTMLCanvasElement>());

  useEffect(() => {
    let cancelled = false;
    taskRef.current?.destroy();
    taskRef.current = null;
    docRef.current = null;
    setPages([]);
    setError(null);
    const load = async () => {
      const headers = new Headers();
      const key = getApiKey();
      if (key) headers.set("Authorization", `Bearer ${key}`);
      const resp = await fetch(url, { headers });
      if (!resp.ok) throw new Error(`HTTP ${resp.status} while loading the PDF`);
      const task = pdfjsLib.getDocument({ data: await resp.arrayBuffer() });
      taskRef.current = task;
      docRef.current = await task.promise;
      const meta: PageMeta[] = [];
      for (let i = 1; i <= docRef.current.numPages; i++) {
        const page = await docRef.current.getPage(i);
        const viewport = page.getViewport({ scale });
        meta.push({ num: i, width: viewport.width, height: viewport.height });
      }
      if (!cancelled) setPages(meta);
    };
    load().catch((err) => {
      if (!cancelled) setError(err instanceof Error ? err.message : String(err));
    });
    return () => {
      cancelled = true;
    };
  }, [url, scale]);

  useEffect(() => {
    if (!pages.length || !docRef.current) return;
    let cancelled = false;
    (async () => {
      for (const meta of pages) {
        if (cancelled) return;
        const canvas = canvases.current.get(meta.num);
        if (!canvas) continue;
        const page = await docRef.current!.getPage(meta.num);
        const viewport = page.getViewport({ scale });
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        await page.render({ canvas, viewport }).promise;
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pages, scale]);

  if (error) {
    return (
      <div className="preview-error">
        <p>Could not render the PDF preview.</p>
        <p className="caption">{error}</p>
      </div>
    );
  }

  if (!pages.length) {
    return <div className="preview-loading">Rendering PDF…</div>;
  }

  return (
    <div className="pdf-viewer">
      {pages.map((meta) => {
        const pos = positions?.find((p) => p.page === meta.num);
        const factor = pos && pos.width > 0 ? meta.width / pos.width : 1;
        return (
          <div key={meta.num} className="pdf-page" style={{ width: meta.width }}>
            <canvas
              ref={(el) => {
                if (el) canvases.current.set(meta.num, el);
                else canvases.current.delete(meta.num);
              }}
              style={{ width: meta.width, height: meta.height }}
              height={meta.height}
            />
            {pos && (
              <div className="pdf-overlay">
                {pos.words.map((word, index) => (
                  <button
                    key={`${meta.num}-${index}`}
                    type="button"
                    className="word-box"
                    title={`Jump to “${word.text}” in the text area`}
                    style={{
                      left: word.x0 * factor,
                      top: word.y0 * factor,
                      width: Math.max(word.x1 - word.x0, 0) * factor,
                      height: Math.max(word.y1 - word.y0, 0) * factor,
                    }}
                    onClick={() => onSelectWord?.(word)}
                  />
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}