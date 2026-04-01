export type ResourceType = 'PDF' | 'Web' | 'Video' | 'Notebook' | 'Other';
export type ResourceOrigin = 'interno' | 'externo';
export type ResourceState = 'OK' | 'AVISO' | 'ERROR';
export type JobLifecycleStatus = 'processing' | 'done' | 'error';
export type ChecklistDecision = 'pending' | 'pass' | 'fail';

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
  progress: number;
  message: string;
  currentStep: number;
  totalSteps: number;
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

export interface GeneratedReport {
  jobId: string;
  resourceCount: number;
  failedItemCount: number;
  groups: ReportGroup[];
  generatedAt: string;
}

export type ReviewResourceType = 'WEB' | 'PDF' | 'VIDEO' | 'NOTEBOOK' | 'IMAGE' | 'OTHER';
export type ReviewResourceHealthStatus = 'OK' | 'WARN' | 'ERROR';
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
  url: string | null;
  path: string | null;
  coursePath: string | null;
  status: ReviewResourceHealthStatus;
  notes: string | null;
  reviewState: ReviewState;
  failCount: number;
  updatedAt: string;
}

export interface ResourceListResponse {
  jobId: string;
  resources: ResourceListItem[];
  reviewSession: ReviewSession;
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

export type ReportSeverity = 'HIGH' | 'MED' | 'LOW';
export type ReportIssueStatus = 'FAIL' | 'PENDING';

export interface ReportFiles {
  pdfUrl: string;
  docxUrl: string;
  jsonUrl: string;
}

export interface ReportStats {
  resources: number;
  fails: number;
  pending: number;
}

export interface ReportMeta {
  reportId: string;
  createdAt: string;
  courseTitle: string | null;
  jobId: string;
  includePending: boolean;
  onlyFails: boolean;
  systemVersion: string;
}

export interface ReportTopResource {
  resourceId: string;
  title: string;
  coursePath: string;
  failCount: number;
}

export interface ReportSummaryData {
  resources: number;
  fails: number;
  pending: number;
  topResources: ReportTopResource[];
  recommendations: string[];
}

export interface ReportIssue {
  itemKey: string;
  label: string;
  description: string;
  recommendation: string | null;
  severity: ReportSeverity;
  status: ReportIssueStatus;
  comment: string | null;
}

export interface ReportResource {
  resourceId: string;
  title: string;
  type: string;
  origin: string;
  status: string;
  source: string | null;
  coursePath: string;
  stats: ReportStats;
  fails: ReportIssue[];
  pending: ReportIssue[];
}

export interface ReportRoute {
  coursePath: string;
  stats: ReportStats;
  resources: ReportResource[];
}

export interface ReportAppendix {
  statusDefinitions: Record<string, string>;
  createdAt: string;
  systemVersion: string;
}

export interface ReportResponse {
  reportId: string;
  createdAt: string;
  files: ReportFiles;
  stats: ReportStats;
  meta: ReportMeta;
  summary: ReportSummaryData;
  routes: ReportRoute[];
  resources: ReportResource[];
  appendix: ReportAppendix;
}

export interface ReportGenerateOptions {
  includePending?: boolean;
  onlyFails?: boolean;
}

const reviewPriority: Record<ReviewState, number> = {
  NEEDS_FIX: 0,
  IN_REVIEW: 1,
  OK: 2,
};

export function sortResourcesByPriority(resources: ResourceListItem[]): ResourceListItem[] {
  return [...resources].sort((left, right) => {
    const priorityDiff = reviewPriority[left.reviewState] - reviewPriority[right.reviewState];
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
    case 'VIDEO':
      return 'Vídeo';
    case 'NOTEBOOK':
      return 'Notebook';
    case 'IMAGE':
      return 'Imagen';
    default:
      return 'Otro';
  }
}

export function getReportSeverityLabel(severity: ReportSeverity): string {
  switch (severity) {
    case 'HIGH':
      return 'Alta';
    case 'MED':
      return 'Media';
    default:
      return 'Baja';
  }
}

export function getReportIssueStatusLabel(status: ReportIssueStatus): string {
  return status === 'FAIL' ? 'No cumple' : 'Pendiente';
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
