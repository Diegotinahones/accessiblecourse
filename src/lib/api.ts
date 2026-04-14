import type {
  CanvasAuth,
  ChecklistSaveRequest,
  ChecklistSaveResult,
  ChecklistTemplatesResponse,
  GeneratedReport,
  JobStatus,
  OnlineCourse,
  ResourceDetailResponse,
  ResourceListItem,
  ResourceListResponse,
  ReviewResourceHealthStatus,
  ReviewResourceType,
  ReviewSession,
  ReviewState,
  ReviewSummary,
} from './types';
import { buildStepMessage } from './utils';

const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') ?? '/api';

interface JobCreatedResponse {
  jobId: string;
}

interface RawJobStatusResponse {
  jobId?: string;
  status: 'created' | 'pending' | 'running' | 'processing' | 'done' | 'error';
  progress: number;
  message?: string;
  currentStep?: number;
  totalSteps?: number;
  errorCode?: string | null;
}

interface RawOnlineCourse {
  id: string;
  name: string;
  term?: string | null;
  start_at?: string | null;
  end_at?: string | null;
}

type RawResourcesResponse = ResourceListResponse | ResourceListItem[];

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

function buildCanvasHeaders(auth: CanvasAuth): HeadersInit {
  return {
    'X-Canvas-Base-Url': auth.baseUrl,
    'X-Canvas-Token': auth.token,
  };
}

function normalizeOnlineCourse(course: RawOnlineCourse): OnlineCourse {
  return {
    id: course.id,
    name: course.name,
    term: course.term ?? null,
    startAt: course.start_at ?? null,
    endAt: course.end_at ?? null,
  };
}

function normalizeReviewType(type: string | null | undefined): ReviewResourceType {
  const value = (type ?? 'OTHER').toUpperCase();

  if (value === 'WEB') {
    return 'WEB';
  }
  if (value === 'PDF') {
    return 'PDF';
  }
  if (value === 'VIDEO') {
    return 'VIDEO';
  }
  if (value === 'NOTEBOOK') {
    return 'NOTEBOOK';
  }
  if (value === 'IMAGE') {
    return 'IMAGE';
  }

  return 'OTHER';
}

function normalizeHealthStatus(status: string | null | undefined): ReviewResourceHealthStatus {
  const value = (status ?? 'OK').toUpperCase();
  if (value === 'WARN' || value === 'AVISO' || value === 'WARNING') {
    return 'WARN';
  }
  if (value === 'ERROR') {
    return 'ERROR';
  }
  return 'OK';
}

function normalizeReviewState(state: string | null | undefined): ReviewState {
  const value = (state ?? 'IN_REVIEW').toUpperCase();
  if (value === 'OK') {
    return 'OK';
  }
  if (value === 'NEEDS_FIX') {
    return 'NEEDS_FIX';
  }
  return 'IN_REVIEW';
}

function normalizeResource(item: ResourceListItem): ResourceListItem {
  return {
    ...item,
    type: normalizeReviewType(item.type),
    status: normalizeHealthStatus(item.status),
    reviewState: normalizeReviewState(item.reviewState),
    origin: item.origin ?? null,
    url: item.url ?? null,
    path: item.path ?? null,
    localPath: item.localPath ?? item.path ?? null,
    coursePath: item.coursePath ?? null,
    notes: item.notes ?? null,
    failCount: item.failCount ?? 0,
  };
}

function deriveReviewSession(jobId: string, resources: ResourceListItem[]): ReviewSession {
  const hasNeedsFix = resources.some((resource) => resource.reviewState === 'NEEDS_FIX');
  const hasOk = resources.some((resource) => resource.reviewState === 'OK');
  const hasReview = resources.some((resource) => resource.reviewState === 'IN_REVIEW');

  const status =
    resources.length === 0 || (hasReview && !hasNeedsFix && !hasOk)
      ? 'NOT_STARTED'
      : hasReview || hasNeedsFix
        ? 'IN_PROGRESS'
        : 'COMPLETE';

  return {
    jobId,
    status,
    startedAt: null,
    updatedAt: new Date().toISOString(),
  };
}

function normalizeResourcesResponse(jobId: string, payload: RawResourcesResponse): ResourceListResponse {
  if (Array.isArray(payload)) {
    const resources = payload.map(normalizeResource);
    return {
      jobId,
      resources,
      reviewSession: deriveReviewSession(jobId, resources),
    };
  }

  const resources = payload.resources.map(normalizeResource);
  return {
    ...payload,
    jobId: payload.jobId ?? jobId,
    resources,
    reviewSession: payload.reviewSession ?? deriveReviewSession(jobId, resources),
  };
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
    const payload = await request<RawJobStatusResponse>(`/jobs/${jobId}`);
    const normalizedStatus =
      payload.status === 'created' || payload.status === 'pending' || payload.status === 'running'
        ? 'processing'
        : payload.status;
    const totalSteps = payload.totalSteps ?? 5;
    const currentStep =
      payload.currentStep ?? Math.min(totalSteps, Math.max(1, Math.ceil(Math.max(payload.progress, 1) / (100 / totalSteps))));

    return {
      status: normalizedStatus,
      progress: payload.progress,
      message: payload.message ?? buildStepMessage(payload.progress),
      currentStep,
      totalSteps,
    };
  },

  async listOnlineCourses(auth: CanvasAuth): Promise<OnlineCourse[]> {
    const payload = await request<RawOnlineCourse[]>('/online/courses', {
      headers: buildCanvasHeaders(auth),
    });
    return payload.map(normalizeOnlineCourse);
  },

  async createOnlineJob(
    payload: { courseId: string; courseName?: string | null },
    auth: CanvasAuth,
  ): Promise<JobCreatedResponse> {
    return request<JobCreatedResponse>('/online/jobs', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...buildCanvasHeaders(auth),
      },
      body: JSON.stringify(payload),
    });
  },
};

export async function fetchResources(jobId: string): Promise<ResourceListResponse> {
  const payload = await request<RawResourcesResponse>(`/jobs/${jobId}/resources`);
  return normalizeResourcesResponse(jobId, payload);
}

export async function fetchResourceDetail(jobId: string, resourceId: string): Promise<ResourceDetailResponse> {
  const payload = await request<ResourceDetailResponse>(`/jobs/${jobId}/resources/${resourceId}`);
  return {
    ...payload,
    resource: normalizeResource(payload.resource),
  };
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

export function fetchReport(jobId: string): Promise<GeneratedReport> {
  return request<GeneratedReport>(`/reports/${jobId}`);
}

export function generateReport(jobId: string): Promise<GeneratedReport> {
  return request<GeneratedReport>(`/reports/${jobId}`, {
    method: 'POST',
  });
}

export function getReportDownloadUrl(path: string): string {
  return resolveApiUrl(path);
}

export function getDirectReportDownloadUrls(jobId: string) {
  return {
    pdf: resolveApiUrl(`/reports/${jobId}/download/pdf`),
    docx: resolveApiUrl(`/reports/${jobId}/download/docx`),
    json: resolveApiUrl(`/reports/${jobId}/download/json`),
  };
}
