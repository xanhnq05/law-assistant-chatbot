import { FileText, Pencil } from "lucide-react";
import { cn } from "@/lib/utils";
import type { DocumentRecord } from "@/services/documentService";

interface DocumentListItemProps {
  doc: DocumentRecord;
  onClick?: () => void;
}

function formatDate(iso?: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleDateString("vi-VN", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}

/**
 * NEW: Badge "Trạng thái hiệu lực" — màu theo trạng thái.
 * active           → xanh emerald
 * partial_expired  → vàng amber
 * expired          → xám slate
 * (other / unset)  → xám slate nhạt
 */
function EffectiveStatusBadge({ status }: { status?: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    active: {
      label: "Còn hiệu lực",
      cls: "bg-emerald-50 text-emerald-700 border-emerald-200",
    },
    partial_expired: {
      label: "Hết hiệu lực một phần",
      cls: "bg-amber-50 text-amber-700 border-amber-200",
    },
    expired: {
      label: "Hết hiệu lực toàn bộ",
      cls: "bg-slate-100 text-slate-600 border-slate-200",
    },
  };
  const cfg = map[status ?? ""] ?? {
    label: "Chưa xác định",
    cls: "bg-slate-50 text-slate-500 border-slate-200",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full border whitespace-nowrap",
        cfg.cls
      )}
      title={`Trạng thái hiệu lực: ${cfg.label}`}
    >
      <span className="w-1.5 h-1.5 rounded-full bg-current opacity-70" />
      {cfg.label}
    </span>
  );
}

/**
 * Vertical list item — bấm vào để mở modal chỉnh sửa.
 */
export default function DocumentListItem({
  doc,
  onClick,
}: DocumentListItemProps) {
  const m = doc.metadata;
  const typeLabel = doc.document_type === "AMENDMENT" ? "Sửa đổi" : "Gốc";

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "group w-full text-left bg-white border border-slate-200 rounded-xl px-4 py-3.5",
        "hover:border-blue-300 hover:shadow-card transition flex items-center gap-4"
      )}
    >
      {/* Icon */}
      <div className="shrink-0 w-10 h-10 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center group-hover:bg-blue-100 transition">
        <FileText className="w-5 h-5" />
      </div>

      {/* Main info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span className="font-mono text-xs text-slate-500 shrink-0">
            {doc.doc_id}
          </span>
          <span className="text-[10px] uppercase tracking-wide font-semibold px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">
            {typeLabel}
          </span>
        </div>
        <h3 className="font-semibold text-slate-900 truncate">{m.title}</h3>
        <p className="text-xs text-slate-500 mt-0.5 truncate">
          {m.document_number || "—"}
          {m.document_number ? " · " : ""}
          {m.issuing_authority || "—"}
          {m.date_enacted ? ` · ban hành ${formatDate(m.date_enacted)}` : ""}
        </p>
      </div>

      {/* Right meta: file count + updated */}
      <div className="hidden md:flex flex-col items-end text-right gap-0.5 shrink-0">
        <span className="text-xs text-slate-500">
          {doc.files.length} file{doc.files.length !== 1 ? "s" : ""}
        </span>
        <span className="text-xs text-slate-400">
          Cập nhật {formatDate(doc.updated_at)}
        </span>
      </div>

      {/* NEW: Effective status badge ở right end */}
      <div className="shrink-0 flex items-center">
        <EffectiveStatusBadge status={m.status} />
      </div>

      <div className="shrink-0 text-slate-300 group-hover:text-blue-600 transition">
        <Pencil className="w-4 h-4" />
      </div>
    </button>
  );
}
