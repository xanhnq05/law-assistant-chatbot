/**
 * Document service - gọi document-service backend.
 */
import { docApi } from "@/lib/services";

export type DocumentType = "ORIGINAL" | "AMENDMENT";
export type ProcessingStatus =
  | "DRAFT"
  | "PROCESSING"
  | "READY"
  | "ACTIVE"
  | "EXPIRED"
  | "FAILED"
  | "AMBIGUOUS";

export interface DocumentMetadata {
  title: string;
  document_type: DocumentType;
  document_number: string;
  document_year: number;
  status: string;
  date_enacted: string;
  date_effective: string;
  issuing_authority: string;
  source?: string;
  version?: string;
  amends_document_id?: string;
}

export interface UploadedFileInfo {
  filename: string;
  supabase_path: string;
  size_bytes: number;
  content_type: string;
  public_url?: string | null;
}

export interface UploadResponse {
  doc_id: string;
  document_type: DocumentType;
  status: ProcessingStatus;
  files: UploadedFileInfo[];
  message: string;
}

export interface DocumentRecord {
  doc_id: string;
  user_id: string;
  document_type: DocumentType;
  status: ProcessingStatus;
  metadata: DocumentMetadata;
  files: UploadedFileInfo[];
  intermediate_json_path?: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentListResponse {
  documents: DocumentRecord[];
  total: number;
}

export interface ProcessingLogEntry {
  stage: string;
  status: string; // "started" | "success" | "error" | "warning"
  message: string;
  timestamp: string;
}

export interface DocumentDetailResponse {
  document: DocumentRecord;
  logs: ProcessingLogEntry[];
}

export type MetadataPatch = Partial<{
  title: string;
  document_number: string;
  document_year: number;
  status: string;
  date_enacted: string;
  date_effective: string;
  issuing_authority: string;
  source: string;
  version: string;
  amends_document_id: string;
}>;

export interface MetadataUpdateResponse {
  doc_id: string;
  document: DocumentRecord;
  message: string;
}

export interface DeleteResponse {
  doc_id: string;
  deleted_files: string[];
  deleted_json_path: string | null;
  message: string;
}

export interface ReparseResponse {
  doc_id: string;
  status: ProcessingStatus;
  message: string;
}

export const documentService = {
  /**
   * Upload nhiều file + metadata trong 1 request multipart.
   */
  async upload(
    files: File[],
    metadata: DocumentMetadata
  ): Promise<UploadResponse> {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    form.append("metadata_json", JSON.stringify(metadata));

    const { data } = await docApi.post<UploadResponse>(
      "/admin/documents/upload",
      form,
      {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 120000, // 2 phút cho upload lớn
      }
    );
    return data;
  },

  async list(limit = 100): Promise<DocumentListResponse> {
    const { data } = await docApi.get<DocumentListResponse>(
      `/admin/documents?limit=${limit}`
    );
    return data;
  },

  async getOne(doc_id: string): Promise<DocumentDetailResponse> {
    const { data } = await docApi.get<DocumentDetailResponse>(
      `/admin/documents/${doc_id}`
    );
    return data;
  },

  async patchMetadata(
    doc_id: string,
    patch: MetadataPatch
  ): Promise<MetadataUpdateResponse> {
    const { data } = await docApi.patch<MetadataUpdateResponse>(
      `/admin/documents/${doc_id}/metadata`,
      patch
    );
    return data;
  },

  async delete(doc_id: string): Promise<DeleteResponse> {
    const { data } = await docApi.delete<DeleteResponse>(
      `/admin/documents/${doc_id}`
    );
    return data;
  },

  async reparse(doc_id: string): Promise<ReparseResponse> {
    const { data } = await docApi.post<ReparseResponse>(
      `/admin/documents/${doc_id}/reparse`
    );
    return data;
  },

  async health(): Promise<{ status: string; service: string }> {
    const { data } = await docApi.get("/admin/health");
    return data;
  },
};
