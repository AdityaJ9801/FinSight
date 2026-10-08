import { useRef, useState, type DragEvent } from "react";
import { FileImage, FileSpreadsheet, FileText, Upload, X } from "lucide-react";
import { useFeedback } from "./feedback";

const ACCEPT = ".csv,.xlsx,.xls,.pdf,.png,.jpg,.jpeg,.webp,.tiff,.bmp";
const SUPPORTED = /\.(csv|xlsx|xls|pdf|png|jpe?g|webp|tiff?|bmp)$/i;

export function fileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** Drop zone + chosen-file list. Rejects unsupported types up front (the API rejects them too)
 * and ignores a second file with the same name. */
export function FilePicker({ files, onChange, id = "file-input", hint }: {
  files: File[];
  onChange: (files: File[]) => void;
  id?: string;
  hint?: string;
}) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const { toast } = useFeedback();

  const add = (list: FileList | File[]) => {
    const incoming = Array.from(list);
    const rejected = incoming.filter((f) => !SUPPORTED.test(f.name));
    if (rejected.length) toast(`Skipped ${rejected.map((f) => f.name).join(", ")}: only CSV, Excel, PDF and Image (PNG, JPG) files are supported.`, "error");
    const names = new Set(files.map((f) => f.name));
    onChange([...files, ...incoming.filter((f) => SUPPORTED.test(f.name) && !names.has(f.name))]);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    add(e.dataTransfer.files);
  };

  return (
    <>
      <div
        className={`drop ${dragging ? "drop-active" : ""} ${files.length ? "drop-has-files" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        // The whole zone opens the picker for pointer users; the "Choose files" button inside
        // is the keyboard path, so this div doesn't need its own tab stop.
        onClick={(e) => { if (!(e.target as HTMLElement).closest("button")) inputRef.current?.click(); }}
      >
        <Upload size={20} strokeWidth={1.75} />
        <div>
          <button type="button" className="link-btn" onClick={() => inputRef.current?.click()}>Choose files</button> or drag them here
        </div>
        <div className="drop-hint">{hint ?? "Balance sheet, P&L, cash flow, bank statements, GST returns. CSV, Excel, PDF or Images (PNG, JPG)."}</div>
        <input id={id} ref={inputRef} type="file" multiple accept={ACCEPT} hidden
          onChange={(e) => { if (e.target.files) add(e.target.files); e.target.value = ""; }} />
      </div>
      {files.length > 0 && (
        <ul className="file-list">
          {files.map((f) => (
            <li key={f.name}>
              {/\.pdf$/i.test(f.name) ? (
                <FileText size={16} />
              ) : /\.(png|jpe?g|webp|tiff?|bmp)$/i.test(f.name) ? (
                <FileImage size={16} />
              ) : (
                <FileSpreadsheet size={16} />
              )}
              <span className="file-name">{f.name}</span>
              <span className="file-size">{fileSize(f.size)}</span>
              <button type="button" className="icon-btn" aria-label={`Remove ${f.name}`} onClick={() => onChange(files.filter((x) => x !== f))}><X size={14} /></button>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
