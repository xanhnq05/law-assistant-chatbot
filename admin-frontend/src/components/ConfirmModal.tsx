import { AlertTriangle } from "lucide-react";

import Modal from "@/components/Modal";

interface ConfirmModalProps {
  open: boolean;
  title: string;
  /** Body của modal — có thể là string hoặc ReactNode cho nội dung phức tạp. */
  children?: React.ReactNode;
  /** Giữ lại để tương thích ngược với callers cũ; nếu có children thì ưu tiên children. */
  message?: React.ReactNode;
  confirmText?: string;
  cancelText?: string;
  /** Tone — destructive sẽ hiển thị icon đỏ + button đỏ. */
  tone?: "destructive" | "default";
  loading?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

/**
 * Modal xác nhận hành động (xoá, hủy, v.v.).
 * - Destructive tone: icon đỏ, button confirm đỏ.
 * - Loading: button confirm disabled + spinner.
 */
export default function ConfirmModal({
  open,
  title,
  children,
  message,
  confirmText = "Xác nhận",
  cancelText = "Huỷ",
  tone = "default",
  loading = false,
  onConfirm,
  onClose,
}: ConfirmModalProps) {
  const isDestructive = tone === "destructive";
  const body = children ?? message;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      maxWidthClass="max-w-md"
      footer={
        <div className="flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={loading}
            className="px-4 py-2 rounded-lg border border-slate-200 bg-white text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 transition"
          >
            {cancelText}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={loading}
            className={`inline-flex items-center gap-2 px-5 py-2 rounded-lg text-white text-sm font-semibold shadow-sm disabled:opacity-50 disabled:cursor-not-allowed transition ${
              isDestructive
                ? "bg-red-600 hover:bg-red-700"
                : "bg-blue-600 hover:bg-blue-700"
            }`}
          >
            {loading && (
              <span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
            )}
            {loading ? "Đang xử lý..." : confirmText}
          </button>
        </div>
      }
    >
      <div className="flex items-start gap-4">
        {isDestructive && (
          <div className="shrink-0 w-10 h-10 rounded-full bg-red-100 text-red-600 flex items-center justify-center">
            <AlertTriangle className="w-5 h-5" />
          </div>
        )}
        <div className="flex-1 text-sm text-slate-700 leading-relaxed">
          {body}
        </div>
      </div>
    </Modal>
  );
}
