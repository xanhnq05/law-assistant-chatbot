interface LoadingOverlayProps {
  open: boolean;
  /** Tiếng Việt message hiển thị dưới spinner. */
  message?: string;
}

/**
 * Loading overlay toàn trang: nền mờ + spinner lớn + message.
 * Khi `open=true`, cấm mọi thao tác (pointer-events-none ở content, chỉ overlay
 * nhận events).
 */
export default function LoadingOverlay({
  open,
  message = "Đang xử lý...",
}: LoadingOverlayProps) {
  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/30 backdrop-blur-[1px]"
      role="dialog"
      aria-modal="true"
      aria-busy="true"
    >
      <div className="bg-white rounded-2xl shadow-xl border border-slate-200 px-8 py-7 flex flex-col items-center gap-4 min-w-[260px]">
        <div className="relative w-12 h-12">
          {/* Vành tròn xoay */}
          <div className="absolute inset-0 rounded-full border-4 border-slate-200" />
          <div className="absolute inset-0 rounded-full border-4 border-blue-600 border-t-transparent animate-spin" />
        </div>
        <p className="text-sm font-medium text-slate-700 text-center">
          {message}
        </p>
        <p className="text-xs text-slate-400 text-center">
          Vui lòng không đóng tab.
        </p>
      </div>
    </div>
  );
}
