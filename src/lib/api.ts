import type {
  CanvasAuth,
  ChecklistSaveRequest,
  ChecklistSaveResult,
  ChecklistTemplatesResponse,
  CourseStructure,
  CourseStructureOrganization,
  CourseStructureNode,
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

interface UploadRequestOptions {
  onProgress?: (progress: number) => void;
}

interface RawJobStatusResponse {
  jobId?: string;
  status: 'created' | 'pending' | 'running' | 'processing' | 'done' | 'error';
  phase?: 'UPLOAD' | 'INVENTORY' | 'ACCESS_SCAN' | 'DONE' | 'ERROR';
  progress: number;
  message?: string;
  currentStep?: number;
  totalSteps?: number;
  errorCode?: string | null;
}

interface RawOnlineCourse {
  id: string | number;
  name: string;
  course_code?: string | null;
  workflow_state?: string | null;
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

function uploadRequest<T>(
  path: string,
  body: FormData,
  options?: UploadRequestOptions,
): Promise<T> {
  const file = body.get('file');
  const fallbackTotal = file instanceof File ? file.size : 0;

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', resolveApiUrl(path));

    xhr.upload.addEventListener('progress', (event) => {
      if (!options?.onProgress) {
        return;
      }

      const total = event.lengthComputable ? event.total : fallbackTotal;
      if (!total) {
        return;
      }

      options.onProgress(Math.min(100, Math.round((event.loaded / total) * 100)));
    });

    xhr.onerror = () => {
      reject(new ApiError(0, 'No se pudo completar la subida del archivo.'));
    };

    xhr.onload = () => {
      const rawText = xhr.responseText || '';
      let payload: unknown = null;

      if (rawText) {
        try {
          payload = JSON.parse(rawText) as unknown;
        } catch {
          payload = null;
        }
      }

      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new ApiError(xhr.status, getErrorMessage(payload)));
        return;
      }

      options?.onProgress?.(100);
      resolve((payload ?? {}) as T);
    };

    xhr.send(body);
  });
}

function buildCanvasHeaders(auth: CanvasAuth): HeadersInit {
  return {
    'X-Canvas-Base-Url': auth.baseUrl,
    'X-Canvas-Token': auth.token,
  };
}

function normalizeOnlineCourse(course: RawOnlineCourse): OnlineCourse {
  return {
    id: String(course.id),
    name: course.name,
    courseCode: course.course_code ?? null,
    workflowState: course.workflow_state ?? null,
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
  const sourceUrl = item.sourceUrl ?? item.url ?? null;
  const downloadUrl = item.downloadUrl ?? null;
  const filePath = item.filePath ?? item.localPath ?? item.path ?? null;
  const modulePath = item.modulePath ?? item.coursePath ?? null;
  const itemPath = item.itemPath ?? null;

  return {
    ...item,
    type: normalizeReviewType(item.type),
    status: normalizeHealthStatus(item.status),
    reviewState: normalizeReviewState(item.reviewState),
    origin: item.origin ?? null,
    url: sourceUrl,
    sourceUrl,
    downloadUrl,
    path: filePath,
    localPath: filePath,
    filePath,
    coursePath: modulePath,
    modulePath,
    itemPath,
    urlStatus: item.urlStatus ?? null,
    finalUrl: item.finalUrl ?? sourceUrl,
    checkedAt: item.checkedAt ?? null,
    canAccess: item.canAccess ?? item.accessStatus === 'OK',
    accessStatus: item.accessStatus ?? (item.status === 'ERROR' ? 'ERROR' : 'OK'),
    httpStatus: item.httpStatus ?? null,
    accessStatusCode: item.accessStatusCode ?? item.httpStatus ?? null,
    canDownload: item.canDownload ?? false,
    downloadStatus: item.downloadStatus ?? (item.canDownload ? 'OK' : 'NO_DESCARGABLE'),
    downloadStatusCode: item.downloadStatusCode ?? null,
    discoveredChildrenCount: item.discoveredChildrenCount ?? 0,
    parentResourceId: item.parentResourceId ?? null,
    discovered: item.discovered ?? false,
    accessNote: item.accessNote ?? item.errorMessage ?? null,
    errorMessage: item.errorMessage ?? null,
    reasonCode: item.reasonCode ?? null,
    reasonDetail: item.reasonDetail ?? null,
    notes: item.notes ?? null,
    failCount: item.failCount ?? 0,
  };
}

function normalizeCourseStructureNode(node: CourseStructureNode): CourseStructureNode {
  return {
    nodeId: node.nodeId ?? node.identifier ?? node.resourceId ?? node.title,
    identifier: node.identifier ?? null,
    title: node.title,
    resourceId: node.resourceId ?? null,
    children: Array.isArray(node.children) ? node.children.map(normalizeCourseStructureNode) : [],
  };
}

function normalizeCourseStructureOrganization(
  organization: CourseStructureOrganization,
): CourseStructureOrganization {
  return {
    nodeId: organization.nodeId ?? organization.identifier ?? organization.title,
    identifier: organization.identifier ?? null,
    title: organization.title,
    children: Array.isArray(organization.children)
      ? organization.children.map(normalizeCourseStructureNode)
      : [],
  };
}

function normalizeCourseStructure(structure: CourseStructure | null | undefined): CourseStructure {
  if (!structure || !Array.isArray(structure.organizations)) {
    return {
      title: 'Estructura del curso',
      organizations: [],
      unplacedResourceIds: [],
    };
  }

  return {
    title: structure.title ?? 'Estructura del curso',
    organizations: structure.organizations.map(normalizeCourseStructureOrganization),
    unplacedResourceIds: Array.isArray(structure.unplacedResourceIds)
      ? structure.unplacedResourceIds.filter((resourceId): resourceId is string => typeof resourceId === 'string')
      : [],
  };
}

function normalizeJobStatus(payload: RawJobStatusResponse): JobStatus {
  const normalizedStatus =
    payload.status === 'created' || payload.status === 'pending' || payload.status === 'running'
      ? 'processing'
      : payload.status;
  const totalSteps = payload.totalSteps ?? 5;
  const currentStep =
    payload.currentStep ??
    Math.min(
      totalSteps,
      Math.max(1, Math.ceil(Math.max(payload.progress, 1) / (100 / totalSteps))),
    );
  let phase = payload.phase;
  if (!phase) {
    if (normalizedStatus === 'done') {
      phase = 'DONE';
    } else if (normalizedStatus === 'error') {
      phase = 'ERROR';
    } else if (currentStep >= totalSteps - 1) {
      phase = 'ACCESS_SCAN';
    } else if (currentStep >= 2) {
      phase = 'INVENTORY';
    } else {
      phase = 'UPLOAD';
    }
  }

  return {
    status: normalizedStatus,
    phase,
    progress: payload.progress,
    message: payload.message ?? buildStepMessage(payload.progress),
    currentStep,
    totalSteps,
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
      structure: normalizeCourseStructure(null),
    };
  }

  const resources = payload.resources.map(normalizeResource);
  const payloadWithLegacyStructure = payload as ResourceListResponse & {
    courseStructure?: CourseStructure | null;
  };
  const rawStructure = payloadWithLegacyStructure.structure ?? payloadWithLegacyStructure.courseStructure ?? null;
  return {
    ...payload,
    jobId: payload.jobId ?? jobId,
    resources,
    reviewSession: payload.reviewSession ?? deriveReviewSession(jobId, resources),
    structure: normalizeCourseStructure(rawStructure),
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
  async createJob(file: File, options?: UploadRequestOptions): Promise<JobCreatedResponse> {
    const formData = new FormData();
    formData.append('file', file);

    return uploadRequest<JobCreatedResponse>('/jobs', formData, options);
  },

  async getJobStatus(jobId: string): Promise<JobStatus> {
    const payload = await request<RawJobStatusResponse>(`/jobs/${jobId}`);
    return normalizeJobStatus(payload);
  },

  async retryJob(jobId: string): Promise<JobStatus> {
    const payload = await request<RawJobStatusResponse>(`/jobs/${jobId}/retry`, {
      method: 'POST',
    });
    return normalizeJobStatus(payload);
  },

  async listOnlineCourses(auth: CanvasAuth): Promise<OnlineCourse[]> {
    const payload = await request<RawOnlineCourse[]>('/online/courses', {
      headers: buildCanvasHeaders(auth),
    });
    return payload.map(normalizeOnlineCourse);
  },

  async listCanvasCourses(): Promise<OnlineCourse[]> {
    const payload = await request<RawOnlineCourse[]>('/canvas/courses');
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

  async createCanvasJob(payload: { courseId: string; courseName?: string | null }): Promise<JobCreatedResponse> {
    return request<JobCreatedResponse>('/canvas/jobs', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });
  },
};

export async function fetchResources(
  jobId: string,
  options?: { onlyBroken?: boolean },
): Promise<ResourceListResponse> {
  const query = options?.onlyBroken ? '?onlyBroken=true' : '';
  const payload = await request<RawResourcesResponse>(`/jobs/${jobId}/resources${query}`);
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

export function getResourceDownloadUrl(jobId: string, resourceId: string) {
  return resolveApiUrl(`/jobs/${jobId}/resources/${resourceId}/download`);
}
