import type {
  ChecklistSaveRequest,
  ChecklistSaveResult,
  ChecklistTemplatesResponse,
  JobStatus,
  ReportGenerateOptions,
  ReportResponse,
  ResourceDetailResponse,
  ResourceListResponse,
  ReviewSummary,
} from './types';

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') ?? '';

interface JobCreatedResponse {
  jobId: string;
}

interface JobStatusResponse {
  jobId: string;
  status: 'created' | 'processing' | 'done' | 'error';
  progress: number;
  message: string;
  currentStep: number;
  totalSteps: number;
  errorCode?: string | null;
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

function getErrorMessage(payload: unknown): string {
  if (payload && typeof payload === 'object') {
    if ('message' in payload && typeof payload.message === 'string') {
      return payload.message;
    }

    if ('detail' in payload && typeof payload.detail === 'string') {
      return payload.detail;
    }
  }

  return 'Ha ocurrido un error inesperado.';
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(resolveApiUrl(path), init);

  if (!response.ok) {
    let message = 'Ha ocurrido un error inesperado.';

    try {
      const payload = (await response.json()) as unknown;
      message = getErrorMessage(payload);
    } catch {
      message = response.statusText || message;
    }

    throw new ApiError(response.status, message);
  }

  return (await response.json()) as T;
}

export function resolveApiUrl(path: string): string {
  if (/^https?:\/\//.test(path)) {
    return path;
  }

  const normalizedPath = path.startsWith('/') ? path : `/${path}`;

  if (!API_BASE_URL) {
    return normalizedPath;
  }

  if (normalizedPath === API_BASE_URL || normalizedPath.startsWith(`${API_BASE_URL}/`)) {
    return normalizedPath;
  }

  return `${API_BASE_URL}${normalizedPath}`;
}

export const api = {
  async createJob(file: File): Promise<JobCreatedResponse> {
    const formData = new FormData();
    formData.append('file', file);

    return request<JobCreatedResponse>('/jobs', {
      method: 'POST',
      body: formData,
    });
  },

  async getJobStatus(jobId: string): Promise<JobStatus> {
    const payload = await request<JobStatusResponse>(`/jobs/${jobId}`);

    return {
      status: payload.status === 'created' ? 'processing' : payload.status,
      progress: payload.progress,
      message: payload.message,
      currentStep: payload.currentStep,
      totalSteps: payload.totalSteps,
    };
  },
};

export function fetchResources(jobId: string): Promise<ResourceListResponse> {
  return request<ResourceListResponse>(`/jobs/${jobId}/resources`);
}

export function fetchResourceDetail(jobId: string, resourceId: string): Promise<ResourceDetailResponse> {
  return request<ResourceDetailResponse>(`/jobs/${jobId}/resources/${resourceId}`);
}

export function fetchChecklistTemplates(): Promise<ChecklistTemplatesResponse> {
  return request<ChecklistTemplatesResponse>('/checklists/templates');
}

export function saveChecklist(
  jobId: string,
  resourceId: string,
  payload: ChecklistSaveRequest,
): Promise<ChecklistSaveResult> {
  return request<ChecklistSaveResult>(`/jobs/${jobId}/resources/${resourceId}/checklist`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
}

export function fetchSummary(jobId: string): Promise<ReviewSummary> {
  return request<ReviewSummary>(`/jobs/${jobId}/summary`);
}

export function fetchReport(jobId: string): Promise<ReportResponse> {
  return request<ReportResponse>(`/jobs/${jobId}/report`);
}

export function generateReport(jobId: string, options?: ReportGenerateOptions): Promise<ReportResponse> {
  return request<ReportResponse>(`/jobs/${jobId}/report`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      includePending: options?.includePending ?? true,
      onlyFails: options?.onlyFails ?? false,
    }),
  });
}

export function getReportDownloadUrl(path: string): string {
  return resolveApiUrl(path);
}
