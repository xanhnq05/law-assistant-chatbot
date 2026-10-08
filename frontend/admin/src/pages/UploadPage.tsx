import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { LogOut, Plus, RefreshCw, ShieldCheck, Inbox, Trash2, RotateCw, AlertTriangle } from "lucide-react";
import { toast } from "sonner";

import FilterBar from "@/components/FilterBar";
import DocumentListItem from "@/components/DocumentListItem";
import DocumentFormModal from "@/components/DocumentFormModal";
import Modal from "@/components/Modal";
import ConfirmModal from "@/components/ConfirmModal";
import LoadingOverlay from "@/components/LoadingOverlay";
import { StatusPill, type StatusFilterValue } from "@/components/StatusBadge";
import {
  documentService,
  type DocumentRecord,
} from "@/services/documentService";
import { useAdminAuth } from "@/store/useAdminAuth";

/**
 * Stage tiếng Việt cho processing logs (dễ đọc hơn so với key snake_case).
 */
const STAGE_LABEL_VI: Record<string, string> = {
  list_originals: "Lấy DS file",
  download: "Tải file",
  extract: "Trích xuất",
  parse: "Phân tích cấu trúc",
  validate: "Kiểm tra schema",
  save: "Lưu JSON",
  neo4j_import: "Import Neo4j",
  neo4j_rels_import: "Import quan hệ Neo4j",
  pinecone_import: "Import Pinecone",
  amendment_detect: "Phát hiện sửa đổi",
  complete: "Hoàn tất",
};

/**
 * Filter tiếng Việt + gộp hết hiệu lực (một phần / toàn bộ) thành 1 nhóm.
 */
const STATUS_FILTERS: { value: StatusFilterValue; label: string }[] = [
  { value: "ALL",              label: "Tất cả" },
  { value: "PROCESSING",       label: "Đang xử lý" },
  { value: "FAILED",           label: "Thất bại" },
  { value: "READY",            label: "Thành công" },
  { value: "ACTIVE_EFFECTIVE", label: "Còn hiệu lực" },
  { value: "EXPIRED",          label: "Hết hiệu lực" },
];

// Polling interval khi có doc PROCESSING (ms)
const POLL_INTERVAL_MS = 3000;

export default function UploadPage() {
  const navigate = useNavigate();
  const user = useAdminAuth((s) => s.user);
  const signOut = useAdminAuth((s) => s.signOut);

  const [docs, setDocs] = useState<DocumentRecord[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilterValue>("ALL");

  // Modal state
  const [createOpen, setCreateOpen] = useState(false);
  const [editDoc, setEditDoc] = useState<DocumentRecord | null>(null);
  const [detailDoc, setDetailDoc] = useState<DocumentRecord | null>(null);
  const [detailLogs, setDetailLogs] = useState<
    { stage: string; status: string; message: string; timestamp: string }[]
  >([]);
  const [loadingDetail, setLoadingDetail] = useState(false);

  // Loading overlay (xoá, re-parse, v.v.)
  const [overlay, setOverlay] = useState<{
    open: boolean;
    message: string;
  }>({ open: false, message: "" });

  // Confirm modal (xoá)
  const [confirmDelete, setConfirmDelete] = useState<DocumentRecord | null>(null);
  const [deleting, setDeleting] = useState(false);

  // NEW: Modal cảnh báo khi xoá bị block bởi amendment con (409 từ backend)
  // Hiển thị danh sách các văn bản sửa đổi đang tham chiếu tới doc gốc
  const [blockedByChildren, setBlockedByChildren] = useState<{
    docId: string;
    message: string;
    children: { doc_id: string; title: string; status: string }[];
  } | null>(null);

  useEffect(() => {
    void fetchDocs();
  }, []);

  async function fetchDocs() {
    setLoadingDocs(true);
    try {
      const res = await documentService.list();
      setDocs(res.documents);
    } catch (err) {
      console.error(err);
      toast.error("Không tải được danh sách văn bản.");
    } finally {
      setLoadingDocs(false);
    }
  }

  // Polling khi có ít nhất 1 doc PROCESSING
  const pollRef = useRef<number | null>(null);
  useEffect(() => {
    const hasProcessing = docs.some((d) => d.status === "PROCESSING");
    if (hasProcessing && pollRef.current === null) {
      pollRef.current = window.setInterval(() => {
        void fetchDocs();
      }, POLL_INTERVAL_MS);
    } else if (!hasProcessing && pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docs]);

  async function handleSignOut() {
    await signOut();
    navigate("/login", { replace: true });
  }

  async function openDetail(doc: DocumentRecord) {
    setDetailDoc(doc);
    setDetailLogs([]);
    setLoadingDetail(true);
    try {
      const res = await documentService.getOne(doc.doc_id);
      setDetailDoc(res.document);
      setDetailLogs(res.logs);
    } catch (err) {
      console.error(err);
      toast.error("Không tải được chi tiết văn bản.");
      setDetailDoc(null);
    } finally {
      setLoadingDetail(false);
    }
  }

  /**
   * NEW: Auto-poll processing logs khi đang mở detail modal của 1 doc PROCESSING.
   * Dừng khi modal đóng HOẶC doc chuyển sang READY/FAILED.
   * Cho phép user xem pipeline progress real-time mà không phải bấm refresh.
   */
  const detailPollRef = useRef<number | null>(null);
  useEffect(() => {
    // Cleanup cũ
    if (detailPollRef.current !== null) {
      window.clearInterval(detailPollRef.current);
      detailPollRef.current = null;
    }
    if (!detailDoc) return;
    if (detailDoc.status !== "PROCESSING") return;

    // Poll logs + status mỗi 2s
    detailPollRef.current = window.setInterval(async () => {
      if (!detailDoc) return;
      try {
        const res = await documentService.getOne(detailDoc.doc_id);
        setDetailLogs(res.logs);
        setDetailDoc(res.document);
        // Tự dừng khi không còn PROCESSING
        if (res.document.status !== "PROCESSING") {
          if (detailPollRef.current !== null) {
            window.clearInterval(detailPollRef.current);
            detailPollRef.current = null;
          }
        }
      } catch (err) {
        // silent — sẽ thử lại ở tick sau
        console.warn("Detail poll failed:", err);
      }
    }, 2000);

    return () => {
      if (detailPollRef.current !== null) {
        window.clearInterval(detailPollRef.current);
        detailPollRef.current = null;
      }
    };
  }, [detailDoc?.doc_id, detailDoc?.status]);

  function askDelete(doc: DocumentRecord) {
    setConfirmDelete(doc);
  }

  async function confirmDeleteAction() {
    if (!confirmDelete) return;
    const target = confirmDelete;
    setDeleting(true);
    setOverlay({ open: true, message: `Đang xoá ${target.doc_id}...` });
    try {
      const res = await documentService.delete(target.doc_id);
      toast.success(
        `Đã xoá ${target.doc_id} (${res.deleted_files.length} file).`
      );
      setDetailDoc(null);
      setConfirmDelete(null);
      await fetchDocs();
    } catch (err: unknown) {
      // NEW: 409 Conflict — backend trả detail là object có child_amendments
      const axiosErr = err as {
        response?: {
          status?: number;
          data?: {
            detail?:
              | string
              | {
                  message?: string;
                  doc_id?: string;
                  child_amendments?: {
                    doc_id: string;
                    title: string;
                    status: string;
                  }[];
                  child_count?: number;
                };
          };
        };
      };
      const detail = axiosErr?.response?.data?.detail;
      if (
        axiosErr?.response?.status === 409 &&
        detail &&
        typeof detail === "object" &&
        "child_amendments" in detail
      ) {
        // Mở modal cảnh báo chuyên biệt thay vì toast
        setBlockedByChildren({
          docId: target.doc_id,
          message: detail.message ?? "Văn bản này đang được tham chiếu.",
          children: detail.child_amendments ?? [],
        });
      } else {
        const msg =
          (err as { response?: { data?: { detail?: string } } })?.response?.data
            ?.detail || (err as Error).message;
        toast.error(`Xoá thất bại: ${msg}`);
      }
    } finally {
      setDeleting(false);
      setOverlay({ open: false, message: "" });
    }
  }

  async function handleReparse(doc: DocumentRecord) {
    setOverlay({ open: true, message: `Đang re-parse ${doc.doc_id}...` });
    try {
      const res = await documentService.reparse(doc.doc_id);
      toast.success(`Re-parse triggered. Status: ${res.status}`);
      if (detailDoc?.doc_id === doc.doc_id) {
        await openDetail(doc);
      }
      await fetchDocs();
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail || (err as Error).message;
      toast.error(`Re-parse thất bại: ${msg}`);
    } finally {
      setOverlay({ open: false, message: "" });
    }
  }

  // Filter + search
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return docs.filter((d) => {
      if (statusFilter === "EXPIRED") {
        if (
          d.metadata.status !== "partial_expired" &&
          d.metadata.status !== "expired"
        ) {
          return false;
        }
      } else if (statusFilter === "ACTIVE_EFFECTIVE") {
        if (d.metadata.status !== "active") return false;
      } else if (statusFilter !== "ALL") {
        if (d.status !== statusFilter) return false;
      }

      if (!q) return true;
      const m = d.metadata;
      return (
        d.doc_id.toLowerCase().includes(q) ||
        m.title.toLowerCase().includes(q) ||
        m.document_number.toLowerCase().includes(q) ||
        m.issuing_authority.toLowerCase().includes(q)
      );
    });
  }, [docs, search, statusFilter]);

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = { ALL: docs.length };
    for (const d of docs) {
      counts[d.status] = (counts[d.status] ?? 0) + 1;
      if (d.metadata.status === "active") {
        counts["ACTIVE_EFFECTIVE"] = (counts["ACTIVE_EFFECTIVE"] ?? 0) + 1;
      }
      if (
        d.metadata.status === "partial_expired" ||
        d.metadata.status === "expired"
      ) {
        counts["EXPIRED"] = (counts["EXPIRED"] ?? 0) + 1;
      }
    }
    return counts;
  }, [docs]);

  return (
    <div className="min-h-screen bg-bgdeep">
      {/* Header */}
      <header className="sticky top-0 z-30 bg-white/80 backdrop-blur border-b border-slate-200">
        <div className="max-w-6xl mx-auto px-6 py-3.5 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-blue-600 text-white flex items-center justify-center shadow-sm">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-base font-semibold text-slate-900 leading-tight">
                Admin · Document Management
              </h1>
              <p className="text-xs text-slate-500">
                Xin chào {user?.name || user?.email || "admin"}{" "}
                <span className="text-blue-600 font-medium">(admin)</span>
              </p>
            </div>
          </div>
          <button
            onClick={handleSignOut}
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm text-slate-600 hover:text-slate-900 hover:bg-slate-100 transition"
          >
            <LogOut className="w-4 h-4" />
            Đăng xuất
          </button>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8 space-y-6">
        {/* Title + actions */}
        <div className="flex items-end justify-between gap-4 flex-wrap">
          <div>
            <h2 className="text-2xl font-bold text-slate-900">
              Văn bản pháp luật
            </h2>
            <p className="text-sm text-slate-500 mt-1">
              Quản lý các văn bản đã được import vào hệ thống.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => void fetchDocs()}
              disabled={loadingDocs}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-slate-200 bg-white text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 transition"
            >
              <RefreshCw
                className={`w-4 h-4 ${loadingDocs ? "animate-spin" : ""}`}
              />
              Refresh
            </button>
            <button
              onClick={() => setCreateOpen(true)}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold shadow-sm transition"
            >
              <Plus className="w-4 h-4" />
              Thêm mới
            </button>
          </div>
        </div>

        {/* Search + filter bar */}
        <div className="space-y-3">
          <FilterBar
            search={search}
            onSearchChange={setSearch}
            searchPlaceholder="Tìm theo tiêu đề, số văn bản, cơ quan ban hành..."
          />

          {/* Status filter pills — tiếng Việt */}
          <div className="flex items-center gap-2 flex-wrap">
            {STATUS_FILTERS.map((f) => (
              <StatusPill
                key={f.value}
                value={f.value}
                active={statusFilter === f.value}
                count={statusCounts[f.value]}
                onClick={() => setStatusFilter(f.value)}
              />
            ))}
          </div>
        </div>

        {/* List */}
        {loadingDocs && docs.length === 0 ? (
          <div className="bg-white border border-slate-200 rounded-xl p-12 text-center">
            <RefreshCw className="w-6 h-6 mx-auto mb-2 animate-spin text-slate-400" />
            <p className="text-sm text-slate-500">Đang tải...</p>
          </div>
        ) : filtered.length === 0 ? (
          <div className="bg-white border border-dashed border-slate-200 rounded-xl p-12 text-center">
            <Inbox className="w-10 h-10 mx-auto mb-3 text-slate-300" />
            <p className="text-slate-700 font-medium">
              {docs.length === 0
                ? "Chưa có văn bản nào."
                : "Không có văn bản nào khớp bộ lọc."}
            </p>
            <p className="text-sm text-slate-500 mt-1">
              {docs.length === 0
                ? 'Bấm "Thêm mới" để upload văn bản đầu tiên.'
                : "Thử đổi từ khoá hoặc bộ lọc trạng thái."}
            </p>
            {docs.length === 0 && (
              <button
                onClick={() => setCreateOpen(true)}
                className="mt-4 inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold transition"
              >
                <Plus className="w-4 h-4" />
                Thêm mới
              </button>
            )}
          </div>
        ) : (
          <div className="space-y-2.5">
            {filtered.map((d) => (
              <DocumentListItem
                key={d.doc_id}
                doc={d}
                onClick={() => openDetail(d)}
              />
            ))}
          </div>
        )}

        {/* Footer info */}
        {!loadingDocs && filtered.length > 0 && (
          <p className="text-xs text-slate-500 text-center pt-2">
            Hiển thị {filtered.length} / {docs.length} văn bản
          </p>
        )}
      </main>

      {/* Create modal — truyền allDocuments để select Document gốc */}
      <DocumentFormModal
        open={createOpen}
        mode="create"
        allDocuments={docs}
        onClose={() => setCreateOpen(false)}
        onSaved={() => {
          setCreateOpen(false);
          // Modal đóng ngay → user thấy doc mới ở status "Đang xử lý"
          // và có thể click vào xem processing log real-time.
          void fetchDocs();
          toast.info("Upload thành công! Pipeline đang xử lý nền — bạn có thể xem log.");
        }}
      />

      {/* Edit modal */}
      <DocumentFormModal
        open={editDoc !== null}
        mode="edit"
        initialDoc={editDoc}
        allDocuments={docs}
        onClose={() => setEditDoc(null)}
        onSaved={() => {
          setEditDoc(null);
          void fetchDocs();
        }}
      />

      {/* Detail modal */}
      <Modal
        open={detailDoc !== null}
        onClose={() => setDetailDoc(null)}
        title={detailDoc?.metadata.title || "Chi tiết văn bản"}
        description={detailDoc ? `${detailDoc.doc_id}` : undefined}
        maxWidthClass="max-w-3xl"
        footer={
          detailDoc && (
            <div className="flex items-center justify-between gap-3">
              <button
                type="button"
                onClick={() => askDelete(detailDoc)}
                disabled={detailDoc.status === "PROCESSING"}
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-red-200 bg-white text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50 disabled:cursor-not-allowed transition"
                title={
                  detailDoc.status === "PROCESSING"
                    ? "Đang xử lý — không thể xoá"
                    : "Xoá vĩnh viễn"
                }
              >
                <Trash2 className="w-4 h-4" />
                Xoá
              </button>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setDetailDoc(null)}
                  className="px-4 py-2 rounded-lg border border-slate-200 bg-white text-sm font-medium text-slate-700 hover:bg-slate-50 transition"
                >
                  Đóng
                </button>
                <button
                  type="button"
                  onClick={() => handleReparse(detailDoc)}
                  disabled={detailDoc.status === "PROCESSING"}
                  className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-slate-200 bg-white text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed transition"
                  title="Chạy lại toàn bộ pipeline (extract → parse → import Neo4j + Pinecone)"
                >
                  <RotateCw className="w-4 h-4" />
                  Parse lại
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setEditDoc(detailDoc);
                    setDetailDoc(null);
                  }}
                  disabled={detailDoc.status === "PROCESSING"}
                  className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold shadow-sm disabled:opacity-50 disabled:cursor-not-allowed transition"
                  title={
                    detailDoc.status === "PROCESSING"
                      ? "Đang xử lý — không thể chỉnh sửa"
                      : "Chỉnh sửa metadata"
                  }
                >
                  Chỉnh sửa
                </button>
              </div>
            </div>
          )
        }
      >
        {loadingDetail ? (
          <div className="py-12 text-center">
            <RefreshCw className="w-6 h-6 mx-auto mb-2 animate-spin text-slate-400" />
            <p className="text-sm text-slate-500">Đang tải...</p>
          </div>
        ) : detailDoc ? (
          <div className="space-y-5">
            <DetailRow label="Số văn bản" value={detailDoc.metadata.document_number} />
            <DetailRow label="Năm" value={detailDoc.metadata.document_year.toString()} />
            <DetailRow
              label="Trạng thái hiệu lực"
              value={effectiveStatusVi(detailDoc.metadata.status)}
            />
            <DetailRow
              label="Trạng thái pipeline"
              value={detailDoc.status}
            />
            <DetailRow
              label="Loại văn bản"
              value={detailDoc.document_type === "AMENDMENT" ? "Sửa đổi" : "Gốc"}
            />
            <DetailRow
              label="Cơ quan ban hành"
              value={detailDoc.metadata.issuing_authority}
            />
            <div className="grid grid-cols-2 gap-4">
              <DetailRow
                label="Ngày ban hành"
                value={detailDoc.metadata.date_enacted}
              />
              <DetailRow
                label="Ngày hiệu lực"
                value={detailDoc.metadata.date_effective}
              />
            </div>
            {detailDoc.metadata.amends_document_id && (
              <DetailRow
                label="Sửa đổi document"
                value={detailDoc.metadata.amends_document_id}
              />
            )}

            <div>
              <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-2">
                Files ({detailDoc.files.length})
              </p>
              <ul className="bg-slate-50 border border-slate-200 rounded-lg p-3 space-y-1.5">
                {detailDoc.files.map((f) => (
                  <li
                    key={f.supabase_path}
                    className="text-xs text-slate-700 flex items-center justify-between gap-2"
                  >
                    <span className="truncate">{f.filename}</span>
                    <span className="text-slate-400 shrink-0">
                      {(f.size_bytes / 1024 / 1024).toFixed(2)} MB
                    </span>
                  </li>
                ))}
              </ul>
            </div>

            {detailLogs.length > 0 && (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">
                    Processing Logs ({detailLogs.length})
                  </p>
                  {detailDoc?.status === "PROCESSING" && (
                    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-blue-600">
                      <span className="relative flex h-2 w-2">
                        <span className="absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75 animate-ping" />
                        <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-600" />
                      </span>
                      Live
                    </span>
                  )}
                </div>
                <ul className="bg-slate-900 border border-slate-700 rounded-lg p-3 space-y-1.5 max-h-56 overflow-y-auto font-mono">
                  {detailLogs.map((l, i) => (
                    <li key={i} className="text-xs leading-relaxed">
                      <span className="text-slate-500">
                        {new Date(l.timestamp).toLocaleTimeString("vi-VN")}
                      </span>{" "}
                      <span
                        className={
                          l.status === "error"
                            ? "text-red-400 font-semibold"
                            : l.status === "warning"
                            ? "text-amber-400 font-semibold"
                            : l.status === "success"
                            ? "text-emerald-400"
                            : "text-slate-400"
                        }
                      >
                        [{STAGE_LABEL_VI[l.stage] ?? l.stage}]
                      </span>{" "}
                      <span className="text-slate-200">{l.message}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Nếu chưa có log nhưng đang PROCESSING → hint */}
            {detailLogs.length === 0 && detailDoc?.status === "PROCESSING" && (
              <div className="bg-slate-50 border border-dashed border-slate-200 rounded-lg p-4 text-center">
                <RefreshCw className="w-4 h-4 mx-auto mb-2 animate-spin text-blue-500" />
                <p className="text-xs text-slate-500">
                  Đang chờ pipeline ghi log đầu tiên...
                </p>
              </div>
            )}
          </div>
        ) : null}
      </Modal>

      {/* Confirm delete modal */}
      <ConfirmModal
        open={confirmDelete !== null}
        title="Xác nhận xoá văn bản"
        tone="destructive"
        confirmText={deleting ? "Đang xoá..." : "Xoá vĩnh viễn"}
        cancelText="Huỷ"
        loading={deleting}
        onConfirm={confirmDeleteAction}
        onClose={() => {
          if (!deleting) setConfirmDelete(null);
        }}
      >
        {confirmDelete && (
          <div className="space-y-2">
            <p>
              Bạn sắp xoá văn bản{" "}
              <span className="font-semibold text-slate-900">
                "{confirmDelete.metadata.title}"
              </span>{" "}
              <span className="font-mono text-xs text-slate-500">
                ({confirmDelete.doc_id})
              </span>
              .
            </p>
            <p className="text-slate-600">
              Hành động này sẽ xoá{" "}
              <span className="font-medium">
                {confirmDelete.files.length} file
              </span>{" "}
              trên Cloud Storage, JSON đã parse, records trong MongoDB, đồ thị
              trong Neo4j và vectors trong Pinecone.
            </p>
            <p className="text-red-600 font-medium">
              Hành động này không thể khôi phục.
            </p>
          </div>
        )}
      </ConfirmModal>

      {/* Loading overlay (xoá, re-parse, v.v.) */}
      <LoadingOverlay open={overlay.open} message={overlay.message} />

      {/* NEW: Modal cảnh báo khi xoá bị block bởi amendment con */}
      <Modal
        open={blockedByChildren !== null}
        onClose={() => setBlockedByChildren(null)}
        title="Không thể xoá văn bản gốc"
        description="Có văn bản sửa đổi đang tham chiếu tới văn bản này."
        maxWidthClass="max-w-lg"
        footer={
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => setBlockedByChildren(null)}
              className="px-4 py-2 rounded-lg border border-slate-200 bg-white text-sm font-medium text-slate-700 hover:bg-slate-50 transition"
            >
              Đã hiểu
            </button>
            {blockedByChildren && blockedByChildren.children.length === 1 && (
              <button
                type="button"
                onClick={() => {
                  const child = blockedByChildren.children[0];
                  setBlockedByChildren(null);
                  // Mở Detail modal của amendment con để user xử lý
                  const childDoc = docs.find((d) => d.doc_id === child.doc_id);
                  if (childDoc) {
                    setDetailDoc(childDoc);
                    void openDetail(childDoc);
                  }
                }}
                className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold shadow-sm transition"
              >
                Mở văn bản sửa đổi
              </button>
            )}
          </div>
        }
      >
        {blockedByChildren && (
          <div className="space-y-4">
            <div className="flex items-start gap-3 bg-amber-50 border border-amber-200 text-amber-900 rounded-lg px-4 py-3 text-sm">
              <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" />
              <p className="leading-relaxed">{blockedByChildren.message}</p>
            </div>
            <div>
              <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-2">
                Văn bản sửa đổi đang tham chiếu ({blockedByChildren.children.length})
              </p>
              <ul className="space-y-1.5">
                {blockedByChildren.children.map((c) => (
                  <li
                    key={c.doc_id}
                    className="bg-slate-50 border border-slate-200 rounded-lg px-3 py-2.5 flex items-center justify-between gap-3"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="font-mono text-xs text-slate-700 truncate">
                        {c.doc_id}
                      </p>
                      <p className="text-sm text-slate-900 truncate">
                        {c.title || "(không có tiêu đề)"}
                      </p>
                    </div>
                    <span className="shrink-0 text-[10px] uppercase tracking-wide font-semibold px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200">
                      {c.status}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="text-xs text-slate-500 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2">
              <p className="font-semibold text-slate-700 mb-1">
                Cách xử lý:
              </p>
              <ol className="list-decimal list-inside space-y-0.5">
                <li>
                  Xoá hết các văn bản sửa đổi ở trên, hoặc
                </li>
                <li>
                  Sửa từng văn bản sửa đổi: đổi <code>Loại văn bản</code> thành{" "}
                  <code>Gốc</code> (nếu còn phù hợp), hoặc chuyển sang tham
                  chiếu văn bản gốc khác.
                </li>
              </ol>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-0.5">
        {label}
      </p>
      <p className="text-sm text-slate-900">{value || "—"}</p>
    </div>
  );
}

function effectiveStatusVi(status?: string): string {
  switch (status) {
    case "active":
      return "Còn hiệu lực";
    case "partial_expired":
      return "Hết hiệu lực một phần";
    case "expired":
      return "Hết hiệu lực toàn bộ";
    default:
      return status || "—";
  }
}
