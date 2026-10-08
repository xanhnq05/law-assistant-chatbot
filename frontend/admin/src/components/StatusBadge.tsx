import { cn } from "@/lib/utils";
import type { ProcessingStatus } from "@/services/documentService";

interface StatusBadgeProps {
  status: string;
  className?: string;
}

/**
 * NEW: Mapping tiếng Việt cho badge — đổi từ raw enum sang nhãn dễ hiểu.
 */
const LABEL_MAP: Record<string, string> = {
  // ProcessingStatus (DB)
  DRAFT: "Chưa xử lý",
  PROCESSING: "Đang xử lý",
  READY: "Thành công",
  ACTIVE: "Đang hoạt động",
  EXPIRED: "Hết hạn",
  FAILED: "Thất bại",
  AMBIGUOUS: "Mơ hồ",
  // Effective status (metadata.status)
  active: "Còn hiệu lực",
  partial_expired: "Hết hiệu lực một phần",
  expired: "Hết hiệu lực toàn bộ",
};

const COLOR_MAP: Record<string, string> = {
  DRAFT: "bg-slate-100 text-slate-700 border-slate-200",
  PROCESSING: "bg-blue-50 text-blue-700 border-blue-200",
  READY: "bg-emerald-50 text-emerald-700 border-emerald-200",
  ACTIVE: "bg-emerald-50 text-emerald-700 border-emerald-200",
  EXPIRED: "bg-slate-100 text-slate-500 border-slate-200",
  FAILED: "bg-red-50 text-red-700 border-red-200",
  AMBIGUOUS: "bg-amber-50 text-amber-700 border-amber-200",
  // metadata.status (effective)
  active: "bg-emerald-50 text-emerald-700 border-emerald-200",
  partial_expired: "bg-amber-50 text-amber-700 border-amber-200",
  expired: "bg-slate-100 text-slate-500 border-slate-200",
};

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const color =
    COLOR_MAP[status] ?? "bg-slate-100 text-slate-600 border-slate-200";
  const label = LABEL_MAP[status] ?? status;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full border whitespace-nowrap",
        color,
        className
      )}
    >
      <span className="w-1.5 h-1.5 rounded-full bg-current opacity-70" />
      {label}
    </span>
  );
}

export type StatusFilterValue =
  | "ALL"
  | ProcessingStatus
  | "active"
  | "partial_expired"
  | "expired"
  | "EXPIRED" // gộp nhóm hết hiệu lực (một phần + toàn bộ)
  | "ACTIVE_EFFECTIVE"; // NEW: riêng nhóm còn hiệu lực (metadata.status=active)

interface StatusPillProps {
  value: StatusFilterValue;
  active: boolean;
  count?: number;
  onClick: () => void;
}

/** NEW: Label tiếng Việt cho pill filter. */
const PILL_LABEL: Record<string, string> = {
  ALL: "Tất cả",
  PROCESSING: "Đang xử lý",
  READY: "Thành công",
  ACTIVE: "Đang hoạt động",
  DRAFT: "Chưa xử lý",
  EXPIRED: "Hết hiệu lực",
  FAILED: "Thất bại",
  AMBIGUOUS: "Mơ hồ",
  active: "Còn hiệu lực",
  partial_expired: "Hết hiệu lực một phần",
  expired: "Hết hiệu lực toàn bộ",
  ACTIVE_EFFECTIVE: "Còn hiệu lực",
};

export function StatusPill({ value, active, count, onClick }: StatusPillProps) {
  const label = PILL_LABEL[value] ?? value;
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-xs font-medium transition",
        active
          ? "bg-blue-600 text-white border-blue-600 shadow-sm"
          : "bg-white text-slate-600 border-slate-200 hover:border-slate-300 hover:bg-slate-50"
      )}
    >
      <span>{label}</span>
      {typeof count === "number" && (
        <span
          className={cn(
            "rounded-full px-1.5 py-0.5 text-[10px] font-semibold",
            active ? "bg-white/20 text-white" : "bg-slate-100 text-slate-500"
          )}
        >
          {count}
        </span>
      )}
    </button>
  );
}
