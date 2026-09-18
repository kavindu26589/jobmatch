import { useEffect, useState } from "react";
import { exportCv } from "../api";
import { useCv } from "../cv";
import { toast } from "./Toast";

const FORMATS = ["pdf", "docx", "txt", "md", "rtf"];

export default function DownloadCV({
  compact = false,
  size = "md",
}: {
  compact?: boolean;
  size?: "md" | "small";
}) {
  const { text, upload } = useCv();
  const [format, setFormat] = useState<string>(upload?.extension ?? "txt");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (upload) setFormat(upload.extension);
  }, [upload]);

  if (!upload) return null;

  const download = async () => {
    if (!upload || busy) return;
    setBusy(true);
    try {
      const result = await exportCv(upload.upload_id, text, format);
      if (!result) {
        toast("Could not generate the file on the server", "err");
        return;
      }
      if (result.notes.length > 0) {
        toast(result.notes.join(" · "), "info");
      }
      const url = URL.createObjectURL(result.blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = result.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      toast(`Saved ${result.filename}`, "ok");
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "err");
    } finally {
      setBusy(false);
    }
  };

  const isDesign = upload.extension === "pdf" || upload.extension === "docx";

  const buttons = (
    <>
      <select
        aria-label="download format"
        value={format}
        onChange={(e) => setFormat(e.target.value)}
      >
        {FORMATS.map((f) => (
          <option key={f} value={f}>
            {f}
            {f === upload.extension ? " (original)" : ""}
          </option>
        ))}
      </select>
      <button
        className={`btn primary ${size === "small" ? "tiny" : ""}`}
        onClick={download}
        disabled={busy}
      >
        {busy ? "Exporting…" : "Download CV"}
      </button>
    </>
  );

  return (
    <div className={`download ${compact ? "compact" : ""} ${size === "small" ? "small" : ""}`}>
      {buttons}
      {isDesign && (
        <div className="caption">
          Exporting as {upload.extension.toUpperCase()} patches your edits into the original design;
          other formats reflow the text.
        </div>
      )}
    </div>
  );
}