import type {
  CanvasAuth,
  ChecklistSaveRequest,
  ChecklistSaveResult,
  ChecklistTemplatesResponse,
  CourseStructure,
  CourseStructureOrganization,
  CourseStructureNode,
  GeneratedReport,
  AccessibilityCheck,
  AccessibilityCheckStatus,
  AccessibilityResource,
  AccessibilityResourceKind,
  AccessibilityResponse,
  AccessibilitySummary,
  JobStatus,
  OnlineCourse,
  ResourceCore,
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
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(
    /\/$/,
    '',
  ) ?? '/api';

interface JobCreatedResponse {
  jobId: string;
}

interface UploadRequestOptions {
  onProgress?: (progress: number) => void;
}

interface RawJobStatusResponse {
  jobId?: string;
  status: 'created' | 'pending' | 'running' | 'processing' | 'done' | 'error';
  phase?:
    | 'UPLOAD'
    | 'INVENTORY'
    | 'ACCESS_SCAN'
    | 'HTML_ACCESSIBILITY_SCAN'
    | 'PDF_ACCESSIBILITY_SCAN'
    | 'DOCX_ACCESSIBILITY_SCAN'
    | 'VIDEO_ACCESSIBILITY_SCAN'
    | 'DONE'
    | 'ERROR';
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

type RawResourceListItem = Partial<ResourceListItem> & Record<string, unknown>;
type RawResourcesResponse =
  | (Omit<ResourceListResponse, 'resources'> & {
      resources: RawResourceListItem[];
    })
  | RawResourceListItem[];

type ResourceAccessStatus = ResourceListItem['accessStatus'];

const ACCESS_STATUSES: ResourceAccessStatus[] = [
  'OK',
  'NO_ACCEDE',
  'REQUIERE_INTERACCION',
  'REQUIERE_SSO',
  'NO_ANALIZABLE',
  'NOT_FOUND',
  'FORBIDDEN',
  'TIMEOUT',
  'ERROR',
];

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

      options.onProgress(
        Math.min(100, Math.round((event.loaded / total) * 100)),
      );
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

function normalizeReviewType(
  type: string | null | undefined,
): ReviewResourceType {
  const value = (type ?? 'OTHER').toUpperCase();

  if (
    value === 'WEB' ||
    value === 'HTML' ||
    value.includes('TEXT/HTML') ||
    value.endsWith('.HTML') ||
    value.endsWith('.HTM')
  ) {
    return 'WEB';
  }
  if (
    value === 'PDF' ||
    value.includes('APPLICATION/PDF') ||
    value.endsWith('.PDF')
  ) {
    return 'PDF';
  }
  if (
    value === 'DOCX' ||
    value === 'WORD' ||
    value.includes('WORDPROCESSINGML') ||
    value.includes('MSWORD') ||
    value.endsWith('.DOCX')
  ) {
    return 'WORD';
  }
  if (value === 'VIDEO') {
    return 'VIDEO';
  }
  if (
    value.includes('VIDEO') ||
    value.includes('YOUTUBE') ||
    value.includes('VIMEO') ||
    value.includes('KALTURA') ||
    value.includes('PANOPTO') ||
    value.endsWith('.MP4') ||
    value.endsWith('.WEBM') ||
    value.endsWith('.MOV')
  ) {
    return 'VIDEO';
  }
  if (value === 'NOTEBOOK') {
    return 'NOTEBOOK';
  }
  if (value === 'IMAGE') {
    return 'IMAGE';
  }
  if (value === 'FILE') {
    return 'FILE';
  }

  return 'OTHER';
}

function readString(value: unknown): string | null {
  if (typeof value === 'string') {
    const trimmedValue = value.trim();
    return trimmedValue || null;
  }

  if (typeof value === 'number') {
    return String(value);
  }

  return null;
}

function readNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }

  if (typeof value === 'string' && value.trim()) {
    const parsedValue = Number(value);
    return Number.isFinite(parsedValue) ? parsedValue : null;
  }

  return null;
}

function readBoolean(value: unknown): boolean | null {
  if (typeof value === 'boolean') {
    return value;
  }

  if (typeof value === 'string') {
    const normalizedValue = value.trim().toLowerCase();
    if (['true', '1', 'yes', 'si', 'sí'].includes(normalizedValue)) {
      return true;
    }
    if (['false', '0', 'no'].includes(normalizedValue)) {
      return false;
    }
  }

  return null;
}

function readArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function readRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object'
    ? (value as Record<string, unknown>)
    : {};
}

function normalizeAccessStatus(
  accessStatus: unknown,
  healthStatus: unknown,
): ResourceAccessStatus {
  const normalizedValue = readString(accessStatus)
    ?.toUpperCase()
    .replace(/\s+/g, '_')
    .replace(/-/g, '_');

  if (normalizedValue === 'NO_ACCEDE' || normalizedValue === 'NO_ACCESIBLE') {
    return 'NO_ACCEDE';
  }

  if (normalizedValue === 'REQUIERE_INTERACCION') {
    return 'REQUIERE_INTERACCION';
  }

  if (normalizedValue === 'REQUIERE_SSO') {
    return 'REQUIERE_SSO';
  }

  if (
    normalizedValue &&
    ACCESS_STATUSES.includes(normalizedValue as ResourceAccessStatus)
  ) {
    return normalizedValue as ResourceAccessStatus;
  }

  const normalizedHealthStatus = readString(healthStatus)?.toUpperCase();
  if (normalizedHealthStatus === 'ERROR') {
    return 'ERROR';
  }

  return 'OK';
}

function normalizeAccessibilityStatus(
  value: unknown,
): AccessibilityCheckStatus {
  const normalizedValue = readString(value)
    ?.toUpperCase()
    .replace(/\s+/g, '_')
    .replace(/-/g, '_');

  if (normalizedValue === 'PASS' || normalizedValue === 'PASSED') {
    return 'PASS';
  }

  if (normalizedValue === 'FAIL' || normalizedValue === 'FAILED') {
    return 'FAIL';
  }

  if (normalizedValue === 'WARNING' || normalizedValue === 'WARN') {
    return 'WARNING';
  }

  if (
    normalizedValue === 'NO_APLICA' ||
    normalizedValue === 'NOT_APPLICABLE' ||
    normalizedValue === 'N_A' ||
    normalizedValue === 'NA'
  ) {
    return 'NO_APLICA';
  }

  return 'ERROR';
}

function normalizeAccessibilityKind(
  value: unknown,
  fallbackKind: AccessibilityResourceKind,
): AccessibilityResourceKind {
  const normalizedValue = readString(value)
    ?.toUpperCase()
    .replace(/\s+/g, '_')
    .replace(/-/g, '_');

  if (!normalizedValue) {
    return fallbackKind;
  }

  if (
    normalizedValue === 'PDF' ||
    normalizedValue.startsWith('PDF_') ||
    normalizedValue.includes('PDF') ||
    normalizedValue.endsWith('.PDF') ||
    normalizedValue.includes('PORTABLE_DOCUMENT')
  ) {
    return 'PDF';
  }

  if (
    normalizedValue === 'WORD' ||
    normalizedValue.startsWith('WORD_') ||
    normalizedValue.startsWith('DOCX_') ||
    normalizedValue.includes('DOCX') ||
    normalizedValue.includes('WORDPROCESSINGML') ||
    normalizedValue.includes('MSWORD') ||
    normalizedValue.endsWith('.DOCX')
  ) {
    return 'WORD';
  }

  if (
    normalizedValue === 'VIDEO' ||
    normalizedValue.startsWith('VIDEO_') ||
    normalizedValue.includes('VIDEO') ||
    normalizedValue.includes('YOUTUBE') ||
    normalizedValue.includes('YOUTU_BE') ||
    normalizedValue.includes('VIMEO') ||
    normalizedValue.includes('KALTURA') ||
    normalizedValue.includes('PANOPTO') ||
    normalizedValue.includes('MEDIA_SITE') ||
    normalizedValue.endsWith('.MP4') ||
    normalizedValue.endsWith('.WEBM') ||
    normalizedValue.endsWith('.MOV')
  ) {
    return 'VIDEO';
  }

  if (
    normalizedValue.includes('HTML') ||
    normalizedValue.includes('WEB') ||
    normalizedValue.includes('PAGE') ||
    normalizedValue.endsWith('.HTM')
  ) {
    return 'HTML';
  }

  return fallbackKind;
}

function normalizeCoreAccessStatus(value: ResourceAccessStatus) {
  if (
    value === 'OK' ||
    value === 'NO_ACCEDE' ||
    value === 'REQUIERE_INTERACCION' ||
    value === 'REQUIERE_SSO' ||
    value === 'NO_ANALIZABLE'
  ) {
    return value;
  }
  return 'NO_ACCEDE';
}

function normalizeReasonCode(value: unknown): ResourceCore['reasonCode'] {
  const normalizedValue = readString(value)?.toUpperCase();
  const validReasonCodes: ResourceCore['reasonCode'][] = [
    'OK',
    'NOT_FOUND',
    'AUTH_REQUIRED',
    'FORBIDDEN',
    'TIMEOUT',
    'DNS_ERROR',
    'SSL_ERROR',
    'NETWORK_ERROR',
    'INVALID_URL',
    'UNKNOWN',
  ];
  if (
    normalizedValue &&
    validReasonCodes.includes(normalizedValue as ResourceCore['reasonCode'])
  ) {
    return normalizedValue as ResourceCore['reasonCode'];
  }
  return 'UNKNOWN';
}

function normalizeDownloadStatus(
  value: unknown,
  downloadable: boolean,
): ResourceCore['downloadStatus'] {
  const normalizedValue = readString(value)?.toUpperCase();
  if (
    normalizedValue === 'OK' ||
    normalizedValue === 'FAIL' ||
    normalizedValue === 'N_A'
  ) {
    return normalizedValue;
  }
  return downloadable ? 'OK' : 'N_A';
}

function normalizeCoreOrigin(
  value: unknown,
  fallbackOrigin: string | null,
): ResourceCore['origin'] {
  const normalizedValue = readString(value)?.toUpperCase();
  const validOrigins: ResourceCore['origin'][] = [
    'ONLINE_CANVAS',
    'OFFLINE_IMSCC',
    'INTERNAL_FILE',
    'INTERNAL_PAGE',
    'EXTERNAL_URL',
    'RALTI',
    'LTI',
  ];
  if (
    normalizedValue &&
    validOrigins.includes(normalizedValue as ResourceCore['origin'])
  ) {
    return normalizedValue as ResourceCore['origin'];
  }
  if (fallbackOrigin === 'externo') {
    return 'EXTERNAL_URL';
  }
  return 'OFFLINE_IMSCC';
}

function normalizeHealthStatus(
  status: string | null | undefined,
): ReviewResourceHealthStatus {
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

function normalizeResourceCore(
  item: RawResourceListItem,
  fallback: {
    id: string;
    title: string;
    type: ReviewResourceType;
    origin: string | null;
    modulePath: string | null;
    sectionTitle: string | null;
    parentResourceId: string | null;
    discovered: boolean;
    accessStatus: ResourceAccessStatus;
    reasonCode: string | null;
    reasonDetail: string | null;
    httpStatus: number | null;
    finalUrl: string | null;
    canDownload: boolean;
    downloadStatus: string | null;
    htmlPath: string | null;
    localPath: string | null;
    sourceUrl: string | null;
  },
): ResourceCore {
  const rawCore =
    item.core && typeof item.core === 'object'
      ? (item.core as unknown as Record<string, unknown>)
      : {};
  const rawModulePath = rawCore.modulePath;
  const modulePath = Array.isArray(rawModulePath)
    ? rawModulePath
        .map((part) => readString(part))
        .filter((part): part is string => Boolean(part))
    : fallback.modulePath
      ? fallback.modulePath
          .split('>')
          .map((part) => part.trim())
          .filter(Boolean)
      : [];
  const coreAccessStatus = normalizeCoreAccessStatus(
    normalizeAccessStatus(rawCore.accessStatus, fallback.accessStatus),
  );
  const downloadable =
    readBoolean(rawCore.downloadable) ?? fallback.canDownload;

  return {
    id: readString(rawCore.id) ?? fallback.id,
    title: readString(rawCore.title) ?? fallback.title,
    type: normalizeReviewType(readString(rawCore.type) ?? fallback.type),
    origin: normalizeCoreOrigin(rawCore.origin, fallback.origin),
    modulePath,
    sectionTitle:
      readString(rawCore.sectionTitle) ?? fallback.sectionTitle ?? null,
    parentId: readString(rawCore.parentId) ?? fallback.parentResourceId,
    discovered: readBoolean(rawCore.discovered) ?? fallback.discovered,
    accessStatus: coreAccessStatus,
    reasonCode: normalizeReasonCode(rawCore.reasonCode ?? fallback.reasonCode),
    reasonDetail:
      readString(rawCore.reasonDetail) ?? fallback.reasonDetail ?? null,
    httpStatus: readNumber(rawCore.httpStatus) ?? fallback.httpStatus,
    finalUrl: readString(rawCore.finalUrl) ?? fallback.finalUrl,
    downloadable,
    downloadStatus: normalizeDownloadStatus(
      rawCore.downloadStatus ?? fallback.downloadStatus,
      downloadable,
    ),
    htmlPath:
      readString(rawCore.htmlPath) ??
      fallback.htmlPath ??
      (normalizeCoreOrigin(rawCore.origin, fallback.origin) === 'INTERNAL_PAGE'
        ? fallback.localPath
        : null),
    localPath: readString(rawCore.localPath) ?? fallback.localPath,
    sourceUrl: readString(rawCore.sourceUrl) ?? fallback.sourceUrl,
    contentAvailable:
      readBoolean(rawCore.contentAvailable) ??
      (coreAccessStatus === 'OK' &&
        (Boolean(fallback.localPath) ||
          Boolean(fallback.htmlPath) ||
          Boolean(fallback.sourceUrl))),
  };
}

function normalizeResource(item: RawResourceListItem): ResourceListItem {
  const accessStatus = normalizeAccessStatus(
    item.accessStatus ?? item.access_status,
    item.status,
  );
  const resourceType =
    readString(item.resourceType) ?? readString(item.resource_type) ?? null;
  const mimeType =
    readString(item.mimeType) ??
    readString(item.mime_type) ??
    readString(item.contentType) ??
    readString(item.content_type) ??
    null;
  const filename =
    readString(item.filename) ??
    readString(item.fileName) ??
    readString(item.file_name) ??
    null;
  const contentKind =
    readString(item.contentKind) ?? readString(item.content_kind) ?? null;
  const provider =
    readString(item.provider) ??
    readString(item.videoProvider) ??
    readString(item.video_provider) ??
    null;
  const videoUrl =
    readString(item.videoUrl) ??
    readString(item.video_url) ??
    readString(item.mediaUrl) ??
    readString(item.media_url) ??
    null;
  const embedUrl =
    readString(item.embedUrl) ??
    readString(item.embed_url) ??
    readString(item.embed) ??
    null;
  const iframe = readString(item.iframe) ?? readString(item.iframeHtml) ?? null;
  const sourceUrl =
    readString(item.sourceUrl) ??
    readString(item.source_url) ??
    readString(item.url) ??
    readString(item.source) ??
    null;
  const downloadUrl =
    readString(item.downloadUrl) ?? readString(item.download_url) ?? null;
  const filePath =
    readString(item.filePath) ??
    readString(item.htmlPath) ??
    readString(item.html_path) ??
    readString(item.localPath) ??
    readString(item.local_path) ??
    readString(item.path) ??
    null;
  const htmlPath =
    readString(item.htmlPath) ??
    readString(item.html_path) ??
    (readString(item.origin)?.toUpperCase() === 'INTERNAL_PAGE' &&
    Boolean(filePath)
      ? filePath
      : null);
  const sectionTitle =
    readString(item.sectionTitle) ??
    readString(item.section_title) ??
    readString(item.section) ??
    null;
  const moduleTitle =
    readString(item.moduleTitle) ??
    readString(item.module_title) ??
    readString(item.module) ??
    readString(item.group) ??
    null;
  const modulePath =
    readString(item.modulePath) ??
    readString(item.module_path) ??
    readString(item.coursePath) ??
    readString(item.course_path) ??
    moduleTitle ??
    sectionTitle ??
    null;
  const sectionKey =
    readString(item.sectionKey) ?? readString(item.section_key) ?? null;
  const itemPath =
    readString(item.itemPath) ?? readString(item.item_path) ?? null;
  const canAccess =
    readBoolean(item.canAccess) ??
    readBoolean(item.can_access) ??
    accessStatus === 'OK';
  const canDownload =
    readBoolean(item.canDownload) ??
    readBoolean(item.can_download) ??
    readBoolean(item.downloadable) ??
    false;
  const reasonCode =
    readString(item.reasonCode) ??
    readString(item.reason_code) ??
    readString(item.accessNote) ??
    readString(item.access_note) ??
    null;
  const reasonDetail =
    readString(item.reasonDetail) ??
    readString(item.reason_detail) ??
    readString(item.errorMessage) ??
    readString(item.error_message) ??
    readString(item.accessNote) ??
    readString(item.access_note) ??
    null;
  const id =
    readString(item.id) ??
    readString(item.resourceId) ??
    readString(item.resource_id) ??
    readString(item.path) ??
    readString(item.url) ??
    readString(item.title) ??
    'resource-unknown';
  const title =
    readString(item.title) ?? readString(item.name) ?? 'Recurso sin título';
  const type = normalizeReviewType(
    readString(item.type) ??
      resourceType ??
      contentKind ??
      provider ??
      videoUrl ??
      embedUrl ??
      iframe ??
      mimeType ??
      filename ??
      filePath,
  );
  const status = normalizeHealthStatus(readString(item.status));
  const reviewState = normalizeReviewState(
    readString(item.reviewState) ?? readString(item.review_state),
  );
  const httpStatus = readNumber(item.httpStatus ?? item.http_status);
  const accessStatusCode = readNumber(
    item.accessStatusCode ?? item.access_status_code ?? item.httpStatus,
  );
  const downloadStatus =
    readString(item.downloadStatus) ??
    readString(item.download_status) ??
    (canDownload ? 'OK' : 'NO_DESCARGABLE');
  const parentResourceId =
    readString(item.parentResourceId) ??
    readString(item.parent_resource_id) ??
    readString(item.parentId) ??
    readString(item.parent_id);
  const discovered = readBoolean(item.discovered) ?? false;
  const contentAvailable =
    readBoolean(item.contentAvailable) ??
    readBoolean(item.content_available) ??
    canDownload;

  return {
    ...item,
    id,
    jobId: readString(item.jobId) ?? readString(item.job_id) ?? '',
    title,
    type,
    resourceType,
    mimeType,
    filename,
    contentKind,
    provider,
    videoUrl,
    embedUrl,
    iframe,
    status,
    reviewState,
    origin: readString(item.origin),
    url: sourceUrl,
    sourceUrl,
    downloadUrl,
    path: filePath,
    htmlPath,
    localPath: filePath,
    filePath,
    coursePath: modulePath,
    modulePath,
    moduleTitle,
    sectionTitle,
    sectionKey,
    sectionType:
      readString(item.sectionType) ?? readString(item.section_type) ?? null,
    itemPath,
    urlStatus: readString(item.urlStatus) ?? readString(item.url_status),
    finalUrl:
      readString(item.finalUrl) ?? readString(item.final_url) ?? sourceUrl,
    checkedAt: readString(item.checkedAt) ?? readString(item.checked_at),
    canAccess,
    accessStatus,
    httpStatus,
    accessStatusCode,
    canDownload,
    downloadStatus,
    downloadStatusCode: readNumber(
      item.downloadStatusCode ?? item.download_status_code,
    ),
    contentAvailable,
    discoveredChildrenCount:
      readNumber(item.discoveredChildrenCount) ??
      readNumber(item.discovered_children_count) ??
      0,
    parentResourceId,
    parentId: parentResourceId,
    discovered,
    accessNote: readString(item.accessNote) ?? readString(item.access_note),
    errorMessage:
      readString(item.errorMessage) ?? readString(item.error_message),
    reasonCode,
    reasonDetail,
    notes: readString(item.notes),
    failCount: readNumber(item.failCount ?? item.fail_count) ?? 0,
    updatedAt:
      readString(item.updatedAt) ??
      readString(item.updated_at) ??
      new Date().toISOString(),
    core: normalizeResourceCore(item, {
      id,
      title,
      type,
      origin: readString(item.origin),
      modulePath,
      sectionTitle,
      parentResourceId,
      discovered,
      accessStatus,
      reasonCode,
      reasonDetail,
      httpStatus: accessStatusCode ?? httpStatus,
      finalUrl:
        readString(item.finalUrl) ?? readString(item.final_url) ?? sourceUrl,
      canDownload,
      downloadStatus,
      htmlPath,
      localPath: filePath,
      sourceUrl,
    }),
  };
}

function normalizeCourseStructureNode(
  node: CourseStructureNode,
): CourseStructureNode {
  return {
    nodeId: node.nodeId ?? node.identifier ?? node.resourceId ?? node.title,
    identifier: node.identifier ?? null,
    title: node.title,
    resourceId: node.resourceId ?? null,
    children: Array.isArray(node.children)
      ? node.children.map(normalizeCourseStructureNode)
      : [],
  };
}

function normalizeCourseStructureOrganization(
  organization: CourseStructureOrganization,
): CourseStructureOrganization {
  return {
    nodeId:
      organization.nodeId ?? organization.identifier ?? organization.title,
    identifier: organization.identifier ?? null,
    title: organization.title,
    children: Array.isArray(organization.children)
      ? organization.children.map(normalizeCourseStructureNode)
      : [],
  };
}

function normalizeCourseStructure(
  structure: CourseStructure | null | undefined,
): CourseStructure {
  if (!structure || !Array.isArray(structure.organizations)) {
    return {
      title: 'Estructura del curso',
      organizations: [],
      unplacedResourceIds: [],
    };
  }

  return {
    title: structure.title ?? 'Estructura del curso',
    organizations: structure.organizations.map(
      normalizeCourseStructureOrganization,
    ),
    unplacedResourceIds: Array.isArray(structure.unplacedResourceIds)
      ? structure.unplacedResourceIds.filter(
          (resourceId): resourceId is string => typeof resourceId === 'string',
        )
      : [],
  };
}

function normalizeJobStatus(payload: RawJobStatusResponse): JobStatus {
  const normalizedStatus =
    payload.status === 'created' ||
    payload.status === 'pending' ||
    payload.status === 'running'
      ? 'processing'
      : payload.status;
  const totalSteps = payload.totalSteps ?? 5;
  const currentStep =
    payload.currentStep ??
    Math.min(
      totalSteps,
      Math.max(
        1,
        Math.ceil(Math.max(payload.progress, 1) / (100 / totalSteps)),
      ),
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

function deriveReviewSession(
  jobId: string,
  resources: ResourceListItem[],
): ReviewSession {
  const hasNeedsFix = resources.some(
    (resource) => resource.reviewState === 'NEEDS_FIX',
  );
  const hasOk = resources.some((resource) => resource.reviewState === 'OK');
  const hasReview = resources.some(
    (resource) => resource.reviewState === 'IN_REVIEW',
  );

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

function normalizeResourcesResponse(
  jobId: string,
  payload: RawResourcesResponse,
): ResourceListResponse {
  if (Array.isArray(payload)) {
    const resources = payload.map(normalizeResource);
    const noAccessByReason = resources.reduce<Record<string, number>>(
      (counts, resource) => {
        if (
          (!resource.canAccess || resource.accessStatus === 'NO_ACCEDE') &&
          resource.reasonCode
        ) {
          counts[resource.reasonCode] = (counts[resource.reasonCode] ?? 0) + 1;
        }
        return counts;
      },
      {},
    );
    return {
      jobId,
      resources,
      totalAnalizables: resources.length,
      noAnalizablesExternos: 0,
      tecnicosIgnorados: 0,
      globalUnplacedCount: resources.filter(
        (resource) => resource.sectionType === 'global_unplaced',
      ).length,
      noAccessCount: resources.filter(
        (resource) =>
          !resource.canAccess || resource.accessStatus === 'NO_ACCEDE',
      ).length,
      noAccessByReason,
      reviewSession: deriveReviewSession(jobId, resources),
      structure: normalizeCourseStructure(null),
    };
  }

  const resources = payload.resources.map(normalizeResource);
  const payloadWithLegacyStructure = payload as ResourceListResponse & {
    courseStructure?: CourseStructure | null;
  };
  const rawStructure =
    payloadWithLegacyStructure.structure ??
    payloadWithLegacyStructure.courseStructure ??
    null;
  return {
    ...payload,
    jobId: payload.jobId ?? jobId,
    resources,
    totalAnalizables: payload.totalAnalizables ?? resources.length,
    noAnalizablesExternos: payload.noAnalizablesExternos ?? 0,
    tecnicosIgnorados: payload.tecnicosIgnorados ?? 0,
    globalUnplacedCount:
      payload.globalUnplacedCount ??
      resources.filter((resource) => resource.sectionType === 'global_unplaced')
        .length,
    noAccessCount:
      payload.noAccessCount ??
      resources.filter(
        (resource) =>
          !resource.canAccess || resource.accessStatus === 'NO_ACCEDE',
      ).length,
    noAccessByReason: payload.noAccessByReason ?? {},
    reviewSession:
      payload.reviewSession ?? deriveReviewSession(jobId, resources),
    structure: normalizeCourseStructure(rawStructure),
  };
}

function normalizeAccessibilityCheck(
  value: unknown,
  index: number,
): AccessibilityCheck {
  const item = readRecord(value);
  const id =
    readString(item.id) ??
    readString(item.checkId) ??
    readString(item.check_id) ??
    readString(item.key) ??
    `check-${index + 1}`;

  return {
    id,
    title:
      readString(item.title) ??
      readString(item.label) ??
      readString(item.name) ??
      `Check ${index + 1}`,
    status: normalizeAccessibilityStatus(
      item.status ??
        item.result ??
        item.outcome ??
        item.accessStatus ??
        item.access_status,
    ),
    evidence:
      readString(item.evidence) ??
      readString(item.detail) ??
      readString(item.details) ??
      null,
    recommendation:
      readString(item.recommendation) ??
      readString(item.recommendationText) ??
      readString(item.recommendation_text) ??
      null,
  };
}

function normalizeAccessibilityResource(
  value: unknown,
  fallbackKind: AccessibilityResourceKind = 'OTHER',
): AccessibilityResource | null {
  const item = readRecord(value);

  if (Object.keys(item).length === 0) {
    return null;
  }

  const resourceId =
    readString(item.resourceId) ??
    readString(item.resource_id) ??
    readString(item.id);

  if (!resourceId) {
    return null;
  }

  const rawChecks =
    readArray(item.checks).length > 0
      ? readArray(item.checks)
      : readArray(item.accessibilityChecks).length > 0
        ? readArray(item.accessibilityChecks)
        : readArray(item.accessibility_checks).length > 0
          ? readArray(item.accessibility_checks)
          : readArray(item.checklist).length > 0
            ? readArray(item.checklist)
            : readArray(item.items).length > 0
              ? readArray(item.items)
              : readArray(item.results);

  return {
    resourceId,
    title: readString(item.title),
    kind: normalizeAccessibilityKind(
      item.kind ??
        item.resourceKind ??
        item.resource_kind ??
        item.analysisType ??
        item.analysis_type ??
        item.scanType ??
        item.scan_type ??
        item.resourceType ??
        item.resource_type ??
        item.mimeType ??
        item.mime_type ??
        item.filename ??
        item.fileName ??
        item.file_name ??
        item.contentKind ??
        item.content_kind ??
        item.provider ??
        item.videoProvider ??
        item.video_provider ??
        item.videoUrl ??
        item.video_url ??
        item.mediaUrl ??
        item.media_url ??
        item.embedUrl ??
        item.embed_url ??
        item.embed ??
        item.iframe ??
        item.iframeHtml ??
        item.type,
      fallbackKind,
    ),
    checks: rawChecks.map(normalizeAccessibilityCheck),
    error:
      readString(item.error) ??
      readString(item.errorMessage) ??
      readString(item.error_message),
  };
}

function mergeAccessibilityResources(
  resources: AccessibilityResource[],
): AccessibilityResource[] {
  const mergedResources = new Map<string, AccessibilityResource>();

  resources.forEach((resource) => {
    const resourceKey = `${resource.kind}:${resource.resourceId}`;
    const existingResource = mergedResources.get(resourceKey);

    if (!existingResource) {
      mergedResources.set(resourceKey, resource);
      return;
    }

    const existingCheckIds = new Set(
      existingResource.checks.map((check) => check.id),
    );
    const nextChecks = [
      ...existingResource.checks,
      ...resource.checks.filter((check) => !existingCheckIds.has(check.id)),
    ];

    mergedResources.set(resourceKey, {
      ...existingResource,
      title: existingResource.title ?? resource.title,
      checks: nextChecks,
      error: existingResource.error ?? resource.error,
    });
  });

  return Array.from(mergedResources.values());
}

function deriveAccessibilitySummary(
  resources: AccessibilityResource[],
): AccessibilitySummary {
  const allChecks = resources.flatMap((resource) => resource.checks);
  const analyzedResources = resources.filter(
    (resource) => resource.checks.length > 0 || resource.error,
  );

  return {
    htmlResourcesAnalyzed: analyzedResources.filter(
      (resource) => resource.kind === 'HTML',
    ).length,
    pdfResourcesAnalyzed: analyzedResources.filter(
      (resource) => resource.kind === 'PDF',
    ).length,
    wordResourcesAnalyzed: analyzedResources.filter(
      (resource) => resource.kind === 'WORD',
    ).length,
    videoResourcesAnalyzed: analyzedResources.filter(
      (resource) => resource.kind === 'VIDEO',
    ).length,
    pass: allChecks.filter((check) => check.status === 'PASS').length,
    warning: allChecks.filter((check) => check.status === 'WARNING').length,
    fail: allChecks.filter((check) => check.status === 'FAIL').length,
    notApplicable: allChecks.filter((check) => check.status === 'NO_APLICA')
      .length,
    errors:
      allChecks.filter((check) => check.status === 'ERROR').length +
      resources.filter((resource) => resource.error).length,
  };
}

function normalizeAccessibilitySummary(
  value: unknown,
  fallbackSummary: AccessibilitySummary,
): AccessibilitySummary {
  const summary = readRecord(value);

  return {
    htmlResourcesAnalyzed:
      readNumber(summary.htmlResourcesAnalyzed) ??
      readNumber(summary.html_resources_analyzed) ??
      readNumber(summary.resourcesHtmlAnalyzed) ??
      readNumber(summary.resources_html_analyzed) ??
      readNumber(readRecord(summary.html).resourcesAnalyzed) ??
      readNumber(readRecord(summary.html).resources_analyzed) ??
      fallbackSummary.htmlResourcesAnalyzed,
    pdfResourcesAnalyzed:
      readNumber(summary.pdfResourcesAnalyzed) ??
      readNumber(summary.pdf_resources_analyzed) ??
      readNumber(summary.resourcesPdfAnalyzed) ??
      readNumber(summary.resources_pdf_analyzed) ??
      readNumber(readRecord(summary.pdf).resourcesAnalyzed) ??
      readNumber(readRecord(summary.pdf).resources_analyzed) ??
      fallbackSummary.pdfResourcesAnalyzed,
    wordResourcesAnalyzed:
      readNumber(summary.wordResourcesAnalyzed) ??
      readNumber(summary.word_resources_analyzed) ??
      readNumber(summary.docxResourcesAnalyzed) ??
      readNumber(summary.docx_resources_analyzed) ??
      readNumber(summary.resourcesWordAnalyzed) ??
      readNumber(summary.resources_word_analyzed) ??
      readNumber(readRecord(summary.word).resourcesAnalyzed) ??
      readNumber(readRecord(summary.word).resources_analyzed) ??
      readNumber(readRecord(summary.docx).resourcesAnalyzed) ??
      readNumber(readRecord(summary.docx).resources_analyzed) ??
      fallbackSummary.wordResourcesAnalyzed,
    videoResourcesAnalyzed:
      readNumber(summary.videoResourcesAnalyzed) ??
      readNumber(summary.video_resources_analyzed) ??
      readNumber(summary.resourcesVideoAnalyzed) ??
      readNumber(summary.resources_video_analyzed) ??
      readNumber(readRecord(summary.video).resourcesAnalyzed) ??
      readNumber(readRecord(summary.video).resources_analyzed) ??
      fallbackSummary.videoResourcesAnalyzed,
    pass:
      readNumber(summary.pass) ??
      readNumber(summary.passed) ??
      readNumber(summary.checksCorrectos) ??
      readNumber(summary.checks_correctos) ??
      fallbackSummary.pass,
    warning:
      readNumber(summary.warning) ??
      readNumber(summary.warnings) ??
      readNumber(summary.avisos) ??
      fallbackSummary.warning,
    fail:
      readNumber(summary.fail) ??
      readNumber(summary.failed) ??
      readNumber(summary.failures) ??
      readNumber(summary.incumplimientos) ??
      fallbackSummary.fail,
    notApplicable:
      readNumber(summary.notApplicable) ??
      readNumber(summary.not_applicable) ??
      readNumber(summary.noAplica) ??
      readNumber(summary.no_aplica) ??
      readNumber(summary.noAplicables) ??
      readNumber(summary.no_aplicables) ??
      fallbackSummary.notApplicable,
    errors:
      readNumber(summary.errors) ??
      readNumber(summary.analysisErrors) ??
      readNumber(summary.analysis_errors) ??
      readNumber(summary.erroresAnalisis) ??
      readNumber(summary.errores_analisis) ??
      fallbackSummary.errors,
  };
}

function emptyAccessibilityResponse(jobId: string): AccessibilityResponse {
  return {
    jobId,
    summary: {
      htmlResourcesAnalyzed: 0,
      pdfResourcesAnalyzed: 0,
      wordResourcesAnalyzed: 0,
      videoResourcesAnalyzed: 0,
      pass: 0,
      warning: 0,
      fail: 0,
      notApplicable: 0,
      errors: 0,
    },
    resources: [],
  };
}

function normalizeAccessibilityResponse(
  jobId: string,
  payload: unknown,
): AccessibilityResponse {
  if (!payload || typeof payload !== 'object') {
    return emptyAccessibilityResponse(jobId);
  }

  const response = payload as Record<string, unknown>;
  const root =
    response.accessibility && typeof response.accessibility === 'object'
      ? (response.accessibility as Record<string, unknown>)
      : response;
  const resourceGroups: Array<{
    fallbackKind: AccessibilityResourceKind;
    resources: unknown[];
  }> = [
    { fallbackKind: 'OTHER', resources: readArray(root.resources) },
    { fallbackKind: 'OTHER', resources: readArray(root.results) },
    { fallbackKind: 'OTHER', resources: readArray(root.items) },
    { fallbackKind: 'HTML', resources: readArray(root.html) },
    { fallbackKind: 'HTML', resources: readArray(root.htmlResources) },
    { fallbackKind: 'HTML', resources: readArray(root.html_resources) },
    { fallbackKind: 'HTML', resources: readArray(root.htmlAccessibility) },
    { fallbackKind: 'HTML', resources: readArray(root.html_accessibility) },
    {
      fallbackKind: 'HTML',
      resources: readArray(readRecord(root.html).resources),
    },
    {
      fallbackKind: 'HTML',
      resources: readArray(readRecord(root.html).results),
    },
    {
      fallbackKind: 'HTML',
      resources: readArray(readRecord(root.htmlAccessibility).resources),
    },
    {
      fallbackKind: 'HTML',
      resources: readArray(readRecord(root.html_accessibility).resources),
    },
    { fallbackKind: 'PDF', resources: readArray(root.pdf) },
    { fallbackKind: 'PDF', resources: readArray(root.pdfResources) },
    { fallbackKind: 'PDF', resources: readArray(root.pdf_resources) },
    { fallbackKind: 'PDF', resources: readArray(root.pdfAccessibility) },
    { fallbackKind: 'PDF', resources: readArray(root.pdf_accessibility) },
    {
      fallbackKind: 'PDF',
      resources: readArray(readRecord(root.pdf).resources),
    },
    { fallbackKind: 'PDF', resources: readArray(readRecord(root.pdf).results) },
    {
      fallbackKind: 'PDF',
      resources: readArray(readRecord(root.pdfAccessibility).resources),
    },
    {
      fallbackKind: 'PDF',
      resources: readArray(readRecord(root.pdf_accessibility).resources),
    },
    { fallbackKind: 'WORD', resources: readArray(root.word) },
    { fallbackKind: 'WORD', resources: readArray(root.docx) },
    { fallbackKind: 'WORD', resources: readArray(root.wordResources) },
    { fallbackKind: 'WORD', resources: readArray(root.word_resources) },
    { fallbackKind: 'WORD', resources: readArray(root.docxResources) },
    { fallbackKind: 'WORD', resources: readArray(root.docx_resources) },
    { fallbackKind: 'WORD', resources: readArray(root.wordAccessibility) },
    { fallbackKind: 'WORD', resources: readArray(root.word_accessibility) },
    { fallbackKind: 'WORD', resources: readArray(root.docxAccessibility) },
    { fallbackKind: 'WORD', resources: readArray(root.docx_accessibility) },
    {
      fallbackKind: 'WORD',
      resources: readArray(readRecord(root.word).resources),
    },
    {
      fallbackKind: 'WORD',
      resources: readArray(readRecord(root.word).results),
    },
    {
      fallbackKind: 'WORD',
      resources: readArray(readRecord(root.docx).resources),
    },
    {
      fallbackKind: 'WORD',
      resources: readArray(readRecord(root.docx).results),
    },
    {
      fallbackKind: 'WORD',
      resources: readArray(readRecord(root.wordAccessibility).resources),
    },
    {
      fallbackKind: 'WORD',
      resources: readArray(readRecord(root.word_accessibility).resources),
    },
    {
      fallbackKind: 'WORD',
      resources: readArray(readRecord(root.docxAccessibility).resources),
    },
    {
      fallbackKind: 'WORD',
      resources: readArray(readRecord(root.docx_accessibility).resources),
    },
    { fallbackKind: 'VIDEO', resources: readArray(root.video) },
    { fallbackKind: 'VIDEO', resources: readArray(root.videos) },
    { fallbackKind: 'VIDEO', resources: readArray(root.videoResources) },
    { fallbackKind: 'VIDEO', resources: readArray(root.video_resources) },
    { fallbackKind: 'VIDEO', resources: readArray(root.videoAccessibility) },
    { fallbackKind: 'VIDEO', resources: readArray(root.video_accessibility) },
    {
      fallbackKind: 'VIDEO',
      resources: readArray(readRecord(root.video).resources),
    },
    {
      fallbackKind: 'VIDEO',
      resources: readArray(readRecord(root.video).results),
    },
    {
      fallbackKind: 'VIDEO',
      resources: readArray(readRecord(root.videoAccessibility).resources),
    },
    {
      fallbackKind: 'VIDEO',
      resources: readArray(readRecord(root.video_accessibility).resources),
    },
  ];
  const resources = mergeAccessibilityResources(
    resourceGroups
      .flatMap(({ fallbackKind, resources: rawResources }) =>
        rawResources.map((resource) =>
          normalizeAccessibilityResource(resource, fallbackKind),
        ),
      )
      .filter((resource): resource is AccessibilityResource =>
        Boolean(resource),
      ),
  );
  const fallbackSummary = deriveAccessibilitySummary(resources);

  return {
    jobId:
      readString(response.jobId) ??
      readString(response.job_id) ??
      readString(root.jobId) ??
      readString(root.job_id) ??
      jobId,
    summary: normalizeAccessibilitySummary(
      root.summary ?? root,
      fallbackSummary,
    ),
    resources,
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

  if (
    normalizedPath === API_BASE_URL ||
    normalizedPath.startsWith(`${API_BASE_URL}/`)
  ) {
    return normalizedPath;
  }

  return `${API_BASE_URL}${normalizedPath}`;
}

export const api = {
  async createJob(
    file: File,
    options?: UploadRequestOptions,
  ): Promise<JobCreatedResponse> {
    const formData = new FormData();
    formData.append('file', file);

    return uploadRequest<JobCreatedResponse>('/jobs', formData, options);
  },

  async getJobStatus(jobId: string): Promise<JobStatus> {
    const payload = await request<RawJobStatusResponse>(`/jobs/${jobId}`);
    return normalizeJobStatus(payload);
  },

  async retryJob(jobId: string): Promise<JobStatus> {
    const payload = await request<RawJobStatusResponse>(
      `/jobs/${jobId}/retry`,
      {
        method: 'POST',
      },
    );
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

  async createCanvasJob(payload: {
    courseId: string;
    courseName?: string | null;
  }): Promise<JobCreatedResponse> {
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
  const payload = await request<RawResourcesResponse>(
    `/jobs/${jobId}/resources${query}`,
  );
  return normalizeResourcesResponse(jobId, payload);
}

export async function fetchAccessibility(
  jobId: string,
): Promise<AccessibilityResponse> {
  try {
    const payload = await request<unknown>(`/jobs/${jobId}/accessibility`);
    return normalizeAccessibilityResponse(jobId, payload);
  } catch (caughtError) {
    if (caughtError instanceof ApiError && caughtError.status === 404) {
      return emptyAccessibilityResponse(jobId);
    }

    throw caughtError;
  }
}

export async function fetchResourceDetail(
  jobId: string,
  resourceId: string,
): Promise<ResourceDetailResponse> {
  const payload = await request<ResourceDetailResponse>(
    `/jobs/${jobId}/resources/${resourceId}`,
  );
  return {
    ...payload,
    resource: normalizeResource(
      payload.resource as unknown as RawResourceListItem,
    ),
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
  return request<ChecklistSaveResult>(
    `/jobs/${jobId}/resources/${resourceId}/checklist`,
    {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    },
  );
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
    pdf: resolveApiUrl(`/jobs/${jobId}/report/download?format=pdf`),
    docx: resolveApiUrl(`/jobs/${jobId}/report/download?format=docx`),
    json: resolveApiUrl(`/jobs/${jobId}/report/download?format=json`),
  };
}

export function getResourceDownloadUrl(jobId: string, resourceId: string) {
  return resolveApiUrl(`/jobs/${jobId}/resources/${resourceId}/download`);
}
