import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  description?: string;
  children: React.ReactNode;
  /** Optional max-width class (default: max-w-3xl) */
  maxWidthClass?: string;
  /** Hide the built-in header (when consumer wants full custom layout) */
  hideHeader?: boolean;
  /** Footer (action buttons) */
  footer?: React.ReactNode;
}

/**
 * Light-theme modal with backdrop, ESC + click-outside to close.
 */
export default function Modal({
  open,
  onClose,
  title,
  description,
  children,
  maxWidthClass = "max-w-3xl",
  hideHeader = false,
  footer,
}: ModalProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null);

  // ESC to close
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  // Lock body scroll while open
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4 py-8 bg-slate-900/40 backdrop-blur-sm"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        className={cn(
          "w-full bg-white rounded-2xl shadow-card-lg border border-slate-200 max-h-[90vh] flex flex-col",
          maxWidthClass
        )}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {!hideHeader && (title || description) && (
          <div className="flex items-start justify-between gap-4 px-6 pt-5 pb-4 border-b border-slate-100">
            <div className="min-w-0">
              {title && (
                <h2 className="text-lg font-semibold text-slate-900 truncate">
                  {title}
                </h2>
              )}
              {description && (
                <p className="mt-1 text-sm text-slate-500">{description}</p>
              )}
            </div>
            <button
              type="button"
              onClick={onClose}
              className="shrink-0 rounded-lg p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition"
              aria-label="Đóng"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>

        {footer && (
          <div className="px-6 py-4 border-t border-slate-100 bg-slate-50/60 rounded-b-2xl">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
