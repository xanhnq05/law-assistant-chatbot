import { useEffect, useMemo, useState } from "react";
import { Upload, RefreshCw } from "lucide-react";
import { toast } from "sonner";

import FileDropzone from "@/components/FileDropzone";
import Modal from "@/components/Modal";
import LoadingOverlay from "@/components/LoadingOverlay";
import {
  documentService,
  type DocumentMetadata,
  type DocumentRecord,
  type DocumentType,
} from "@/services/documentService";
import { displayToIsoDate, isoToDisplayDate, maskDateInput } from "@/lib/utils";

const DOCUMENT_TYPES: { value: DocumentType; label: string }[] = [
  { value: "ORIGINAL", label: "Văn bản gốc" },
  { value: "AMENDMENT", label: "Văn bản sửa đổi / bổ sung" },
];

// NEW: Cơ quan ban hành — 2 option cố định + fallback cho giá trị cũ không khớp
const ISSUING_AUTHORITIES = [
  { value: "Chính phủ", label: "Chính phủ" },
  { value: "Quốc hội", label: "Quốc hội" },
] as const;

const ISSUING_AUTHORITY_VALUES = ISSUING_AUTHORITIES.map((a) => a.value);

// NEW: Trạng thái hiệu lực — 3 option tiếng Việt (mapping sang 3 value backend)
// Backend chỉ chấp nhận 3 giá trị: active / partial_expired / expired
const STATUS_OPTIONS = [
  { value: "active",           label: "Còn hiệu lực" },
  { value: "partial_expired",  label: "Hết hiệu lực một phần" },
  { value: "expired",          label: "Hết hiệu lực toàn bộ" },
] as const;

type StatusValue = (typeof STATUS_OPTIONS)[number]["value"];

const STATUS_VALUES: readonly StatusValue[] = STATUS_OPTIONS.map(
  (s) => s.value
) as readonly StatusValue[];

interface DocumentFormModalProps {
  open: boolean;
  mode: "create" | "edit";
  initialDoc?: DocumentRecord | null;
  /** List các Document khác để chọn làm "Document gốc" khi type=AMENDMENT. */
  allDocuments?: DocumentRecord[];
  onClose: () => void;
  onSaved: () => void;
}

interface FormState {
  files: File[];
  docType: DocumentType;
  title: string;
  docNumber: string;
  docYear: number;
  status: StatusValue;
  dateEnacted: string;
  dateEffective: string;
  issuingAuthority: string;
  amendsDocumentId: string;
}

function emptyForm(): FormState {
  return {
    files: [],
    docType: "ORIGINAL",
    title: "",
    docNumber: "",
    docYear: new Date().getFullYear(),
    status: "active",
    dateEnacted: "",
    dateEffective: "",
    issuingAuthority: "Chính phủ", // NEW: default = Chính phủ
    amendsDocumentId: "",
  };
}

/**
 * Stub autofill: gợi ý năm + số văn bản + title từ tên file.
 */
function autofillFromFiles(
  files: File[],
  setForm: React.Dispatch<React.SetStateAction<FormState>>
) {
  if (files.length === 0) return;
  const yearMatch = files[0].name.match(/((?:19|20)\d{2})/);
  if (yearMatch) {
    setForm((prev) => ({
      ...prev,
      docYear: parseInt(yearMatch[1], 10),
      docNumber: prev.docNumber || extractDocNumber(files[0].name),
      title:
        prev.title ||
        files[0].name
          .replace(/\.(pdf|docx?)$/i, "")
          .replace(/[_-]+/g, " ")
          .trim(),
    }));
  }
}

function extractDocNumber(filename: string): string {
  const m = filename.match(/(\d{1,4}\/\d{4}\/[A-ZĐ]+-[A-Z]+|\d{1,4}-\d{4}-[A-ZĐ-]+)/);
  return m ? m[1] : "";
}

export default function DocumentFormModal({
  open,
  mode,
  initialDoc,
  allDocuments,
  onClose,
  onSaved,
}: DocumentFormModalProps) {
  const [form, setForm] = useState<FormState>(emptyForm());
  const [submitting, setSubmitting] = useState(false);
  const [customAuthority, setCustomAuthority] = useState<string>("");
  // NEW: State cho hiển thị ngày dạng dd/mm/yyyy (state nội bộ vẫn giữ YYYY-MM-DD)
  const [dateEnactedDisplay, setDateEnactedDisplay] = useState<string>("");
  const [dateEffectiveDisplay, setDateEffectiveDisplay] = useState<string>("");

  // isEdit phải được tính TRƯỚC khi dùng cho isDocProcessing
  const isEdit = mode === "edit";
  /**
   * NEW: Khi edit document đang ở status PROCESSING (parser/importer đang chạy
   * trong background) thì phải disable toàn bộ form + nút submit để tránh
   * user spam bấm "Lưu thay đổi" / sửa metadata gây race với pipeline.
   * Chỉ được phép edit khi status ∈ {READY, ACTIVE, EXPIRED, FAILED, AMBIGUOUS}.
   */
  const isDocProcessing =
    isEdit && initialDoc?.status === "PROCESSING";
  /**
   * NEW: Nếu document cũ có `issuing_authority` không thuộc 2 option cố định
   * (vd "Chính phủ nước CHXHCNVN" từ data cũ), ta lưu vào state này để hiển thị
   * option "Khác (giá trị cũ)" trong select — tránh mất data khi edit.
   */

  // Khi mở modal edit: prefill từ initialDoc
  useEffect(() => {
    if (!open) return;
    if (mode === "edit" && initialDoc) {
      const m = initialDoc.metadata;
      // Map status value từ backend -> form
      const statusValue: StatusValue = (STATUS_VALUES as readonly string[]).includes(
        m.status
      )
        ? (m.status as StatusValue)
        : "active";
      // Detect nếu issuing_authority cũ không khớp 2 option cố định
      const iaRaw = m.issuing_authority ?? "";
      const iaKnown = (ISSUING_AUTHORITY_VALUES as readonly string[]).includes(iaRaw);
      const custom = iaKnown ? "" : iaRaw;
      setCustomAuthority(custom);
      setForm({
        files: [],
        docType: initialDoc.document_type,
        title: m.title ?? "",
        docNumber: m.document_number ?? "",
        docYear: m.document_year ?? new Date().getFullYear(),
        status: statusValue,
        dateEnacted: m.date_enacted ?? "",
        dateEffective: m.date_effective ?? "",
        issuingAuthority: iaRaw || "Chính phủ",
        amendsDocumentId: m.amends_document_id ?? "",
      });
      setDateEnactedDisplay(isoToDisplayDate(m.date_enacted ?? ""));
      setDateEffectiveDisplay(isoToDisplayDate(m.date_effective ?? ""));
    } else if (mode === "create") {
      setCustomAuthority("");
      setForm(emptyForm());
      setDateEnactedDisplay("");
      setDateEffectiveDisplay("");
    }
  }, [open, mode, initialDoc]);

  // Auto-fill stub khi user chọn file (chỉ trong create mode)
  function handleFilesChange(files: File[]) {
    setForm((prev) => ({ ...prev, files }));
    if (mode === "create") {
      autofillFromFiles(files, setForm);
    }
  }

  /**
   * Validation ngày ở frontend (mirror backend):
   * - date_enacted <= today
   * - date_effective >= date_enacted
   * Return null nếu OK, hoặc message lỗi.
   */
  const dateError = useMemo<string | null>(() => {
    if (!form.dateEnacted || !form.dateEffective) return null;
    const dEnacted = new Date(form.dateEnacted);
    const dEffective = new Date(form.dateEffective);
    if (Number.isNaN(dEnacted.getTime()) || Number.isNaN(dEffective.getTime())) {
      return "Ngày không hợp lệ.";
    }
    const today = new Date();
    today.setHours(23, 59, 59, 999); // so sánh theo ngày
    if (dEnacted > today) {
      return "Ngày ban hành không được nằm trong tương lai.";
    }
    if (dEffective < dEnacted) {
      return "Ngày có hiệu lực không được sớm hơn ngày ban hành.";
    }
    return null;
  }, [form.dateEnacted, form.dateEffective]);

  // Lọc documents khác để chọn làm "Document gốc" (khi edit thì bỏ chính nó)
  const amendableDocs = useMemo(() => {
    if (!allDocuments) return [];
    return allDocuments.filter(
      (d) => d.document_type === "ORIGINAL" && d.doc_id !== initialDoc?.doc_id
    );
  }, [allDocuments, initialDoc]);

  async function handleSubmit() {
    // Common metadata validation
    if (
      !form.title ||
      !form.docNumber ||
      !form.dateEnacted ||
      !form.dateEffective ||
      !form.issuingAuthority
    ) {
      toast.error("Vui lòng điền đầy đủ metadata bắt buộc.");
      return;
    }

    // Date validation (frontend)
    if (dateError) {
      toast.error(dateError);
      return;
    }

    // NOTE: Không strict-check issuing_authority ở frontend.
    // Backend chấp nhận bất kỳ string nào (giữ tương thích với data cũ).
    // Select chỉ gợi ý 2 option phổ biến nhất, nhưng cho phép user nhập
    // giá trị khác (option "Khác" hiển thị ở edit mode nếu data cũ không khớp).

    if (mode === "create") {
      if (form.files.length === 0) {
        toast.error("Vui lòng chọn ít nhất 1 file.");
        return;
      }
      if (form.docType === "AMENDMENT" && !form.amendsDocumentId) {
        toast.error("Văn bản sửa đổi cần chỉ định Document gốc.");
        return;
      }
    } else {
      if (form.docType === "AMENDMENT" && !form.amendsDocumentId) {
        toast.error("Văn bản sửa đổi cần chỉ định Document gốc.");
        return;
      }
    }

    setSubmitting(true);
    try {
      if (mode === "create") {
        const metadata: DocumentMetadata = {
          title: form.title,
          document_type: form.docType,
          document_number: form.docNumber,
          document_year: form.docYear,
          status: form.status,
          date_enacted: form.dateEnacted,
          date_effective: form.dateEffective,
          issuing_authority: form.issuingAuthority,
          amends_document_id:
            form.docType === "AMENDMENT" ? form.amendsDocumentId : undefined,
        };
        const res = await documentService.upload(form.files, metadata);
        toast.success(
          `Upload thành công! doc_id=${res.doc_id}, status=${res.status}`
        );
      } else {
        const patch: Record<string, unknown> = {
          title: form.title,
          document_number: form.docNumber,
          document_year: form.docYear,
          status: form.status,
          date_enacted: form.dateEnacted,
          date_effective: form.dateEffective,
          issuing_authority: form.issuingAuthority,
        };
        if (form.docType === "AMENDMENT" && form.amendsDocumentId) {
          patch.amends_document_id = form.amendsDocumentId;
        }
        const res = await documentService.patchMetadata(initialDoc!.doc_id, patch);
        toast.success(`Đã cập nhật metadata cho ${res.doc_id}`);
      }
      onSaved();
      onClose();
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail || (err as Error).message;
      toast.error(`${mode === "create" ? "Upload" : "Cập nhật"} thất bại: ${msg}`);
    } finally {
      setSubmitting(false);
    }
  }

  const titleText = isEdit
    ? `Chỉnh sửa văn bản: ${initialDoc?.metadata.title ?? initialDoc?.doc_id}`
    : "Thêm văn bản mới";

  // Gom logic disable: disable khi đang submit HOẶC đang processing
  const formDisabled = submitting || isDocProcessing;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={titleText}
      description={
        isEdit
          ? "Cập nhật metadata cho văn bản này."
          : "Upload file PDF/DOCX và điền metadata. Các trường sẽ tự động được gợi ý khi chọn file."
      }
      maxWidthClass="max-w-4xl"
      footer={
        <div className="flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={formDisabled}
            className="px-4 py-2 rounded-lg border border-slate-200 bg-white text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 transition"
          >
            Huỷ
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={formDisabled}
            className="inline-flex items-center gap-2 px-5 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold shadow-sm disabled:opacity-50 disabled:cursor-not-allowed transition"
          >
            {submitting ? (
              <>
                <RefreshCw className="w-4 h-4 animate-spin" />
                Đang xử lý...
              </>
            ) : isDocProcessing ? (
              <>
                <RefreshCw className="w-4 h-4 animate-spin" />
                Đang xử lý — không thể lưu
              </>
            ) : isEdit ? (
              "Lưu thay đổi"
            ) : (
              <>
                <Upload className="w-4 h-4" />
                Upload
              </>
            )}
          </button>
        </div>
      }
    >
      <div className="space-y-6">
        {/* Banner cảnh báo khi document đang được pipeline xử lý */}
        {isDocProcessing && (
          <div className="flex items-start gap-3 bg-amber-50 border border-amber-200 text-amber-800 rounded-lg px-4 py-3 text-sm">
            <RefreshCw className="w-4 h-4 mt-0.5 animate-spin shrink-0" />
            <div>
              <p className="font-semibold">Văn bản đang được xử lý</p>
              <p className="text-amber-700 mt-0.5">
                Pipeline parse / import đang chạy trong nền. Vui lòng đợi đến
                khi trạng thái chuyển sang <b>READY</b> (hoặc <b>FAILED</b>) thì
                mới chỉnh sửa được. Không tải lại trang kẻo mất tiến trình.
              </p>
            </div>
          </div>
        )}

        {/* Document Type */}
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">
            Loại văn bản
          </label>
          <div className="flex gap-3">
            {DOCUMENT_TYPES.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setForm((p) => ({ ...p, docType: opt.value }))}
                disabled={submitting || isEdit}
                className={`flex-1 px-4 py-3 rounded-lg border text-sm font-medium transition ${
                  form.docType === opt.value
                    ? "border-blue-500 bg-blue-50 text-blue-700"
                    : "border-slate-200 bg-white text-slate-700 hover:border-slate-300"
                } disabled:opacity-50`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* File Dropzone (create only) */}
        {!isEdit && (
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-2">
              File PDF / DOCX
            </label>
            <FileDropzone
              files={form.files}
              onChange={handleFilesChange}
              disabled={formDisabled}
            />
            <p className="text-xs text-slate-500 mt-2">
              Có thể upload nhiều file cho cùng 1 Document. Tên file phải
              duy nhất trong request.
            </p>
          </div>
        )}

        {isEdit && initialDoc && (
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-2">
              File hiện tại
            </label>
            <ul className="space-y-1.5 bg-slate-50 border border-slate-200 rounded-lg p-3">
              {initialDoc.files.map((f) => (
                <li
                  key={f.supabase_path}
                  className="text-xs text-slate-600 flex items-center justify-between"
                >
                  <span className="truncate">{f.filename}</span>
                  <span className="text-slate-400">
                    {(f.size_bytes / 1024 / 1024).toFixed(2)} MB
                  </span>
                </li>
              ))}
            </ul>
            <p className="text-xs text-slate-500 mt-2">
              Thay thế file chưa hỗ trợ trong Phase này.
            </p>
          </div>
        )}

        {/* Metadata */}
        <div>
          <h3 className="text-sm font-semibold text-slate-700 mb-3">
            Metadata
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Field
              label="Tiêu đề *"
              value={form.title}
              onChange={(v) => setForm((p) => ({ ...p, title: v }))}
              disabled={formDisabled}
            />
            <Field
              label="Số văn bản *"
              value={form.docNumber}
              onChange={(v) => setForm((p) => ({ ...p, docNumber: v }))}
              placeholder="VD: 168/2024/NĐ-CP"
              disabled={formDisabled}
            />
            <Field
              label="Năm *"
              type="number"
              value={form.docYear.toString()}
              onChange={(v) =>
                setForm((p) => ({
                  ...p,
                  docYear: parseInt(v) || new Date().getFullYear(),
                }))
              }
              disabled={formDisabled}
            />

            {/* Trạng thái hiệu lực (tiếng Việt) */}
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">
                Trạng thái hiệu lực
              </label>
              <select
                value={form.status}
                onChange={(e) =>
                  setForm((p) => ({
                    ...p,
                    status: e.target.value as StatusValue,
                  }))
                }
                disabled={formDisabled}
                className="w-full rounded-lg bg-white border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:opacity-50"
              >
                {STATUS_OPTIONS.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Ngày ban hành — format dd/mm/yyyy, payload YYYY-MM-DD */}
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">
                Ngày ban hành *
              </label>
              <input
                type="text"
                inputMode="numeric"
                placeholder="dd/mm/yyyy"
                value={dateEnactedDisplay}
                onChange={(e) => {
                  const masked = maskDateInput(e.target.value);
                  setDateEnactedDisplay(masked);
                  const iso = displayToIsoDate(masked);
                  // Chỉ commit vào form khi user gõ đủ 8 số và hợp lệ
                  setForm((p) => ({ ...p, dateEnacted: iso ?? "" }));
                }}
                onBlur={() => {
                  // Nếu blur mà chưa hợp lệ → clear để tránh submit sai
                  if (
                    dateEnactedDisplay &&
                    !displayToIsoDate(dateEnactedDisplay)
                  ) {
                    setDateEnactedDisplay("");
                    setForm((p) => ({ ...p, dateEnacted: "" }));
                  }
                }}
                disabled={formDisabled}
                className="w-full rounded-lg bg-white border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:opacity-50"
              />
              <p className="text-xs text-slate-500 mt-1">
                Định dạng: dd/mm/yyyy (vd: 15/10/2024). Không được ở tương lai.
              </p>
            </div>

            {/* Ngày có hiệu lực — format dd/mm/yyyy, payload YYYY-MM-DD */}
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">
                Ngày có hiệu lực *
              </label>
              <input
                type="text"
                inputMode="numeric"
                placeholder="dd/mm/yyyy"
                value={dateEffectiveDisplay}
                onChange={(e) => {
                  const masked = maskDateInput(e.target.value);
                  setDateEffectiveDisplay(masked);
                  const iso = displayToIsoDate(masked);
                  setForm((p) => ({ ...p, dateEffective: iso ?? "" }));
                }}
                onBlur={() => {
                  if (
                    dateEffectiveDisplay &&
                    !displayToIsoDate(dateEffectiveDisplay)
                  ) {
                    setDateEffectiveDisplay("");
                    setForm((p) => ({ ...p, dateEffective: "" }));
                  }
                }}
                disabled={formDisabled}
                className="w-full rounded-lg bg-white border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:opacity-50"
              />
              <p className="text-xs text-slate-500 mt-1">
                Định dạng: dd/mm/yyyy. Phải sau hoặc bằng ngày ban hành.
              </p>
            </div>

            {/* Cơ quan ban hành — SELECT với 2 option cố định + fallback cho data cũ */}
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">
                Cơ quan ban hành *
              </label>
              <select
                value={form.issuingAuthority}
                onChange={(e) =>
                  setForm((p) => ({ ...p, issuingAuthority: e.target.value }))
                }
                disabled={formDisabled}
                className="w-full rounded-lg bg-white border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:opacity-50"
              >
                {ISSUING_AUTHORITIES.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
                {customAuthority &&
                  !ISSUING_AUTHORITY_VALUES.includes(
                    form.issuingAuthority as typeof ISSUING_AUTHORITY_VALUES[number]
                  ) && (
                    <option value={customAuthority}>
                      Khác — {customAuthority}
                    </option>
                  )}
              </select>
              <p className="text-xs text-slate-500 mt-1">
                Gợi ý 2 cơ quan phổ biến nhất. Nếu cần giá trị khác, nhập trực
                tiếp khi tạo mới.
              </p>
            </div>

            {/* Document gốc (khi AMENDMENT) — SELECT từ allDocuments */}
            {form.docType === "AMENDMENT" && (
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  Document gốc bị sửa đổi *
                </label>
                <select
                  value={form.amendsDocumentId}
                  onChange={(e) =>
                    setForm((p) => ({ ...p, amendsDocumentId: e.target.value }))
                  }
                  disabled={formDisabled}
                  className="w-full rounded-lg bg-white border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:opacity-50"
                >
                  <option value="">-- Chọn document gốc --</option>
                  {amendableDocs.map((d) => (
                    <option key={d.doc_id} value={d.doc_id}>
                      {d.doc_id} — {d.metadata.title}
                    </option>
                  ))}
                </select>
                {amendableDocs.length === 0 && (
                  <p className="text-xs text-amber-600 mt-1">
                    Chưa có Document gốc nào trong hệ thống.
                  </p>
                )}
              </div>
            )}
          </div>

          {/* Date error message */}
          {dateError && (
            <p className="mt-3 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              {dateError}
            </p>
          )}
        </div>
      </div>

      {/* Loading overlay khi đang submit — file lớn có thể mất vài giây */}
      <LoadingOverlay
        open={submitting}
        message={
          submitting
            ? mode === "create"
              ? "Đang upload file và khởi tạo pipeline..."
              : "Đang lưu metadata..."
            : ""
        }
      />
    </Modal>
  );
}

// ---------- helpers ----------
function Field({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  disabled,
  min,
  max,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  placeholder?: string;
  disabled?: boolean;
  min?: string;
  max?: string;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-slate-700 mb-1">
        {label}
      </label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        min={min}
        max={max}
        className="w-full rounded-lg bg-white border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:opacity-50"
      />
    </div>
  );
}
