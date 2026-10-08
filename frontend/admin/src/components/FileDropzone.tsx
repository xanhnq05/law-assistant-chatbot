import { useCallback, useRef, useState } from "react";
import { UploadCloud, FileText, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface FileDropzoneProps {
  files: File[];
  onChange: (files: File[]) => void;
  accept?: string;
  multiple?: boolean;
  disabled?: boolean;
  maxSizeMB?: number;
}

const DEFAULT_ACCEPT =
  ".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

export default function FileDropzone({
  files,
  onChange,
  accept = DEFAULT_ACCEPT,
  multiple = true,
  disabled = false,
  maxSizeMB = 50,
}: FileDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFiles = useCallback(
    (incoming: FileList | File[]) => {
      setError(null);
      const arr = Array.from(incoming);
      for (const f of arr) {
        if (f.size > maxSizeMB * 1024 * 1024) {
          setError(`File "${f.name}" vượt quá ${maxSizeMB} MB.`);
          return;
        }
      }
      if (multiple) {
        onChange([...files, ...arr]);
      } else {
        onChange(arr.slice(0, 1));
      }
    },
    [files, onChange, multiple, maxSizeMB]
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDragOver(false);
      if (disabled) return;
      if (e.dataTransfer.files?.length) {
        handleFiles(e.dataTransfer.files);
      }
    },
    [handleFiles, disabled]
  );

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(true);
  }, []);

  const onDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
  }, []);

  const removeFile = (idx: number) => {
    if (disabled) return;
    onChange(files.filter((_, i) => i !== idx));
  };

  return (
    <div className="space-y-3">
      <div
        onDrop={onDrop}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onClick={() => !disabled && inputRef.current?.click()}
        className={cn(
          "rounded-xl border-2 border-dashed transition cursor-pointer p-8 text-center select-none bg-white",
          dragOver
            ? "border-blue-500 bg-blue-50"
            : "border-slate-300 hover:border-blue-400 hover:bg-blue-50/30",
          disabled && "opacity-50 cursor-not-allowed"
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          multiple={multiple}
          disabled={disabled}
          onChange={(e) => e.target.files && handleFiles(e.target.files)}
          className="hidden"
        />
        <UploadCloud className="w-10 h-10 mx-auto mb-3 text-blue-500" />
        <p className="font-medium text-slate-800">
          {dragOver ? "Thả file vào đây..." : "Kéo thả file PDF/DOC/DOCX vào đây"}
        </p>
        <p className="text-sm text-slate-500 mt-1">
          hoặc click để chọn file (tối đa {maxSizeMB}MB / file)
        </p>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      {files.length > 0 && (
        <div className="space-y-2">
          <p className="text-sm font-medium text-slate-700">
            Đã chọn {files.length} file{files.length > 1 ? "s" : ""}:
          </p>
          <ul className="space-y-1">
            {files.map((f, idx) => (
              <li
                key={`${f.name}-${idx}`}
                className="flex items-center gap-2 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-sm"
              >
                <FileText className="w-4 h-4 text-blue-500 shrink-0" />
                <span className="flex-1 truncate text-slate-700">{f.name}</span>
                <span className="text-xs text-slate-400">
                  {(f.size / 1024 / 1024).toFixed(2)} MB
                </span>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    removeFile(idx);
                  }}
                  disabled={disabled}
                  className="text-slate-400 hover:text-red-600 disabled:opacity-30 transition"
                >
                  <X className="w-4 h-4" />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
