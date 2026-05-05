export type ResourceType = 'PDF' | 'Web' | 'Video' | 'Notebook' | 'Other';
export type ResourceOrigin = 'interno' | 'externo';
export type ResourceState = 'OK' | 'AVISO' | 'ERROR';
export type JobLifecycleStatus =
  | 'pending'
  | 'running'
  | 'processing'
  | 'done'
  | 'error';
export type JobPhase =
  | 'UPLOAD'
  | 'INVENTORY'
  | 'ACCESS_SCAN'
  | 'HTML_ACCESSIBILITY_SCAN'
  | 'PDF_ACCESSIBILITY_SCAN'
  | 'DOCX_ACCESSIBILITY_SCAN'
  | 'DONE'
  | 'ERROR';
export type ChecklistDecision = 'pending' | 'pass' | 'fail';
export type AnalysisMode = 'offline' | 'online';
export type AppMode = 'online' | 'offline';

export interface Resource {
  id: string;
  title: string;
  type: ResourceType;
  origin: ResourceOrigin;
  status: ResourceState;
}

export interface ChecklistItem {
  id: string;
  label: string;
  recommendation: string;
}

export type ResourceChecklistState = Record<string, ChecklistDecision>;
export type ChecklistState = Record<string, ResourceChecklistState>;

export interface JobStatus {
  status: JobLifecycleStatus;
  phase: JobPhase;
  progress: number;
  message: string;
  currentStep: number;
  totalSteps: number;
}

export interface CanvasAuth {
  baseUrl: string;
  token: string;
  authMode?: 'token';
}

export interface OnlineCourse {
  id: string;
  name: string;
  courseCode: string | null;
  workflowState: string | null;
  term: string | null;
  startAt: string | null;
  endAt: string | null;
}

export interface ReportFailure {
  itemId: string;
  label: string;
  recommendation: string;
}

export interface ReportGroup {
  resource: Resource;
  failures: ReportFailure[];
}

export interface ReportDownloads {
  pdfUrl: string;
  docxUrl: string;
}

export interface GeneratedReport {
  jobId: string;
  resourceCount: number;
  failedItemCount: number;
  groups: ReportGroup[];
  generatedAt: string;
  downloads: ReportDownloads;
}

export type ReviewResourceType =
  | 'WEB'
  | 'PDF'
  | 'WORD'
  | 'VIDEO'
  | 'NOTEBOOK'
  | 'IMAGE'
  | 'FILE'
  | 'OTHER';
export type ReviewResourceHealthStatus = 'OK' | 'WARN' | 'ERROR';
export type ResourceCoreOrigin =
  | 'ONLINE_CANVAS'
  | 'OFFLINE_IMSCC'
  | 'INTERNAL_FILE'
  | 'INTERNAL_PAGE'
  | 'EXTERNAL_URL'
  | 'RALTI'
  | 'LTI';
export type ResourceCoreAccessStatus =
  | 'OK'
  | 'NO_ACCEDE'
  | 'REQUIERE_SSO'
  | 'REQUIERE_INTERACCION'
  | 'NO_ANALIZABLE';
export type ResourceCoreReasonCode =
  | 'OK'
  | 'NOT_FOUND'
  | 'AUTH_REQUIRED'
  | 'FORBIDDEN'
  | 'TIMEOUT'
  | 'DNS_ERROR'
  | 'SSL_ERROR'
  | 'NETWORK_ERROR'
  | 'INVALID_URL'
  | 'UNKNOWN';
export type ResourceCoreDownloadStatus = 'OK' | 'FAIL' | 'N_A';
export interface ResourceCore {
  id: string;
  title: string;
  type: ReviewResourceType;
  origin: ResourceCoreOrigin;
  modulePath: string[];
  sectionTitle: string | null;
  parentId: string | null;
  discovered: boolean;
  accessStatus: ResourceCoreAccessStatus;
  reasonCode: ResourceCoreReasonCode;
  reasonDetail: string | null;
  httpStatus: number | null;
  finalUrl: string | null;
  downloadable: boolean;
  downloadStatus: ResourceCoreDownloadStatus;
  htmlPath: string | null;
  localPath: string | null;
  sourceUrl: string | null;
  contentAvailable: boolean;
}
export type ReviewState = 'OK' | 'IN_REVIEW' | 'NEEDS_FIX';
export type ReviewChecklistValue = 'PENDING' | 'PASS' | 'FAIL';
export type ReviewSessionStatus = 'NOT_STARTED' | 'IN_PROGRESS' | 'COMPLETE';
export interface ReviewSession {
  jobId: string;
  status: ReviewSessionStatus;
  startedAt: string | null;
  updatedAt: string;
}

export interface ResourceListItem {
  id: string;
  jobId: string;
  title: string;
  type: ReviewResourceType;
  origin: string | null;
  analysisCategory?: string;
  resourceType?: string | null;
  mimeType?: string | null;
  filename?: string | null;
  contentKind?: string | null;
  url: string | null;
  sourceUrl: string | null;
  downloadUrl: string | null;
  path: string | null;
  htmlPath: string | null;
  localPath: string | null;
  filePath: string | null;
  coursePath: string | null;
  modulePath: string | null;
  moduleTitle?: string | null;
  sectionTitle?: string | null;
  sectionKey?: string | null;
  sectionType?: string | null;
  itemPath: string | null;
  status: ReviewResourceHealthStatus;
  urlStatus: string | null;
  finalUrl: string | null;
  checkedAt: string | null;
  canAccess: boolean;
  accessStatus:
    | 'OK'
    | 'NO_ACCEDE'
    | 'REQUIERE_INTERACCION'
    | 'REQUIERE_SSO'
    | 'NO_ANALIZABLE'
    | 'NOT_FOUND'
    | 'FORBIDDEN'
    | 'TIMEOUT'
    | 'ERROR';
  httpStatus: number | null;
  accessStatusCode: number | null;
  canDownload: boolean;
  downloadStatus: string | null;
  downloadStatusCode: number | null;
  contentAvailable: boolean;
  discoveredChildrenCount: number;
  parentResourceId: string | null;
  parentId: string | null;
  discovered: boolean;
  accessNote: string | null;
  errorMessage: string | null;
  reasonCode?: string | null;
  reasonDetail?: string | null;
  notes: string | null;
  reviewState: ReviewState;
  failCount: number;
  updatedAt: string;
  core: ResourceCore;
}

export interface CourseStructureNode {
  nodeId: string;
  identifier: string | null;
  title: string;
  resourceId: string | null;
  children: CourseStructureNode[];
}

export interface CourseStructureOrganization {
  nodeId: string;
  identifier: string | null;
  title: string;
  children: CourseStructureNode[];
}

export interface CourseStructure {
  title: string;
  organizations: CourseStructureOrganization[];
  unplacedResourceIds: string[];
}

export interface ResourceListResponse {
  jobId: string;
  resources: ResourceListItem[];
  totalAnalizables?: number;
  noAnalizablesExternos?: number;
  tecnicosIgnorados?: number;
  globalUnplacedCount?: number;
  noAccessCount?: number;
  noAccessByReason?: Record<string, number>;
  reviewSession: ReviewSession;
  structure: CourseStructure;
}

export type AccessibilityResourceKind = 'HTML' | 'PDF' | 'WORD' | 'OTHER';

export type AccessibilityCheckStatus =
  | 'PASS'
  | 'FAIL'
  | 'WARNING'
  | 'NO_APLICA'
  | 'ERROR';

export interface AccessibilityCheck {
  id: string;
  title: string;
  status: AccessibilityCheckStatus;
  evidence: string | null;
  recommendation: string | null;
}

export interface AccessibilityResource {
  resourceId: string;
  title: string | null;
  kind: AccessibilityResourceKind;
  checks: AccessibilityCheck[];
  error: string | null;
}

export interface AccessibilitySummary {
  htmlResourcesAnalyzed: number;
  pdfResourcesAnalyzed: number;
  wordResourcesAnalyzed: number;
  pass: number;
  warning: number;
  fail: number;
  notApplicable: number;
  errors: number;
}

export interface AccessibilityResponse {
  jobId: string;
  summary: AccessibilitySummary;
  resources: AccessibilityResource[];
}

export interface ChecklistTemplateItem {
  itemKey: string;
  label: string;
  description: string | null;
  recommendation: string | null;
}

export interface ChecklistTemplate {
  templateId: string;
  resourceType: ReviewResourceType;
  items: ChecklistTemplateItem[];
}

export interface ChecklistTemplatesResponse {
  templates: Partial<Record<ReviewResourceType, ChecklistTemplate>>;
}

export interface ReviewChecklistItem {
  itemKey: string;
  label: string;
  description: string | null;
  recommendation: string | null;
  value: ReviewChecklistValue;
  comment: string | null;
}

export interface ResourceDetailResponse {
  resource: ResourceListItem;
  checklist: {
    templateId: string;
    resourceType: ReviewResourceType;
    items: ReviewChecklistItem[];
  };
  reviewSession: ReviewSession;
}

export interface ChecklistSaveRequest {
  responses: Array<{
    itemKey: string;
    value: ReviewChecklistValue;
    comment?: string;
  }>;
}

export interface ChecklistSaveResult {
  resourceId: string;
  reviewState: ReviewState;
  failCount: number;
  updatedAt: string;
}

export interface ReviewRecommendation {
  itemKey: string;
  label: string;
  recommendation: string | null;
  comment: string | null;
}

export interface ReviewFailResource {
  resourceId: string;
  title: string;
  resourceType: ReviewResourceType;
  reviewState: ReviewState;
  failCount: number;
  recommendations: ReviewRecommendation[];
}

export interface ReviewSummary {
  jobId: string;
  totalResources: number;
  totalFailItems: number;
  lastUpdated: string;
  reviewSession: ReviewSession;
  resources: ReviewFailResource[];
}

const reviewPriority: Record<ReviewState, number> = {
  NEEDS_FIX: 0,
  IN_REVIEW: 1,
  OK: 2,
};

export function sortResourcesByPriority(
  resources: ResourceListItem[],
): ResourceListItem[] {
  return [...resources].sort((left, right) => {
    const priorityDiff =
      reviewPriority[left.reviewState] - reviewPriority[right.reviewState];
    if (priorityDiff !== 0) {
      return priorityDiff;
    }

    return left.title.localeCompare(right.title, 'es');
  });
}

export function getReviewStateLabel(state: ReviewState): string {
  switch (state) {
    case 'OK':
      return 'OK';
    case 'NEEDS_FIX':
      return 'Requiere cambios';
    default:
      return 'En revisión';
  }
}

export function getReviewResourceTypeLabel(type: ReviewResourceType): string {
  switch (type) {
    case 'WEB':
      return 'Web';
    case 'PDF':
      return 'PDF';
    case 'WORD':
      return 'Word';
    case 'VIDEO':
      return 'Vídeo';
    case 'NOTEBOOK':
      return 'Notebook';
    case 'IMAGE':
      return 'Imagen';
    case 'FILE':
      return 'Archivo';
    default:
      return 'Otro';
  }
}

export function getSessionStatusLabel(status: ReviewSessionStatus): string {
  switch (status) {
    case 'NOT_STARTED':
      return 'Sin empezar';
    case 'COMPLETE':
      return 'Completada';
    default:
      return 'En curso';
  }
}

export function formatDate(isoDate: string | null): string {
  if (!isoDate) {
    return 'Sin fecha';
  }

  return new Intl.DateTimeFormat('es-ES', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(isoDate));
}
