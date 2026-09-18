import { originalFileUrl } from "../api";
import type { PdfPageBoxes, PdfWordBox, UploadResult } from "../types";
import DocxPreview from "./DocxPreview";
import PdfViewer from "./PdfViewer";

export default function ResumePreview({
  upload,
  positions,
  onSelectWord,
}: {
  upload: UploadResult;
  positions: PdfPageBoxes[] | null;
  onSelectWord?: (word: PdfWordBox) => void;
}) {
  const url = originalFileUrl(upload.upload_id);
  if (upload.extension === "pdf") {
    return <PdfViewer url={url} positions={positions} onSelectWord={onSelectWord} />;
  }
  if (upload.extension === "docx") {
    return <DocxPreview url={url} />;
  }
  return (
    <div className="preview-error">
      <p className="caption">No design preview for {upload.extension.toUpperCase()} files — the text
        area is the editor.</p>
    </div>
  );
}