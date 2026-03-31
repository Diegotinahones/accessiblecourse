import type {
  ChecklistSaveRequest,
  ChecklistSaveResult,
  ChecklistTemplatesResponse,
  ReportResponse,
  ResourceDetailResponse,
  ResourceListResponse,
  ReviewSummary,
} from './types';

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') ?? '';

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);

  if (!response.ok) {
    let message = 'Ha ocurrido un error inesperado.';

    try {
      const payload = (await response.json()) as { detail?: string };
      message = payload.detail ?? message;
    } catch {
      message = response.statusText || message;
    }

    throw new ApiError(response.status, message);
  }

  return (await response.json()) as T;
}

export function fetchResources(jobId: string): Promise<ResourceListResponse> {
  return request<ResourceListResponse>(`/api/jobs/${jobId}/resources`);
}

export function fetchResourceDetail(jobId: string, resourceId: string): Promise<ResourceDetailResponse> {
  return request<ResourceDetailResponse>(`/api/jobs/${jobId}/resources/${resourceId}`);
}

export function fetchChecklistTemplates(): Promise<ChecklistTemplatesResponse> {
  return request<ChecklistTemplatesResponse>('/api/checklists/templates');
}

export function saveChecklist(
  jobId: string,
  resourceId: string,
  payload: ChecklistSaveRequest,
): Promise<ChecklistSaveResult> {
  return request<ChecklistSaveResult>(`/api/jobs/${jobId}/resources/${resourceId}/checklist`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
}

export function fetchSummary(jobId: string): Promise<ReviewSummary> {
  return request<ReviewSummary>(`/api/jobs/${jobId}/summary`);
}

export function exportReport(jobId: string): Promise<ReportResponse> {
  return request<ReportResponse>(`/api/jobs/${jobId}/report`, {
    method: 'POST',
  });
}
