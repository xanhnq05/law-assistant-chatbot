import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Convert "YYYY-MM-DD" (ISO) -> "dd/mm/yyyy" (display).
 * Trả về chuỗi rỗng nếu input rỗng hoặc không hợp lệ.
 */
export function isoToDisplayDate(iso: string): string {
  if (!iso) return "";
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return "";
  return `${m[3]}/${m[2]}/${m[1]}`;
}

/**
 * Parse chuỗi người dùng nhập (dd/mm/yyyy) -> "YYYY-MM-DD" (ISO).
 * Chấp nhận các dạng: "dd/mm/yyyy", "dd-mm-yyyy", "dd.mm.yyyy".
 * Tự điền mask khi user gõ: "dd/mm/yyyy" là output khi đủ 8 số.
 * Trả về null nếu không phải ngày hợp lệ.
 */
export function displayToIsoDate(input: string): string | null {
  if (!input) return null;
  // Lấy tất cả chữ số, bỏ qua ký tự phân cách
  const digits = input.replace(/\D/g, "");
  if (digits.length === 0) return null;
  if (digits.length < 8) return null; // chưa đủ ngày/tháng/năm
  const dd = digits.slice(0, 2);
  const mm = digits.slice(2, 4);
  const yyyy = digits.slice(4, 8);

  const dayNum = parseInt(dd, 10);
  const monthNum = parseInt(mm, 10);
  const yearNum = parseInt(yyyy, 10);
  if (monthNum < 1 || monthNum > 12) return null;
  if (dayNum < 1 || dayNum > 31) return null;
  if (yearNum < 1900 || yearNum > 9999) return null;

  // Validate ngày/tháng/năm có tồn tại thật (vd 31/02 là invalid)
  const isoCandidate = `${yyyy}-${mm}-${dd}`;
  const d = new Date(isoCandidate);
  if (
    Number.isNaN(d.getTime()) ||
    d.getFullYear() !== yearNum ||
    d.getMonth() + 1 !== monthNum ||
    d.getDate() !== dayNum
  ) {
    return null;
  }
  return isoCandidate;
}

/**
 * Mask khi user đang gõ: chèn "/" sau dd và mm.
 * - "1"  -> "1"
 * - "12" -> "12"
 * - "120" -> "12/0"
 * - "1202" -> "12/02"
 * - "120220" -> "12/02/20"
 * - "12022024" -> "12/02/2024"
 * - "120220241" -> "120220241" (giữ nguyên, cho phép user sửa)
 */
export function maskDateInput(raw: string): string {
  const digits = raw.replace(/\D/g, "").slice(0, 8);
  if (digits.length <= 2) return digits;
  if (digits.length <= 4) return `${digits.slice(0, 2)}/${digits.slice(2)}`;
  return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`;
}
