export type ResourceType = 'WEB' | 'PDF' | 'VIDEO' | 'NOTEBOOK' | 'OTHER';
export type ResourceHealthStatus = 'OK' | 'WARN' | 'ERROR';
export type ReviewState = 'OK' | 'IN_REVIEW' | 'NEEDS_FIX';
export type ChecklistValue = 'PENDING' | 'PASS' | 'FAIL';
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
  type: ResourceType;
  origin: string | null;
  url: string | null;
  path: string | null;
  coursePath: string | null;
  status: ResourceHealthStatus;
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

export interface ChecklistItem {
  itemKey: string;
  label: string;
  description: string | null;
  recommendation: string | null;
  value: ChecklistValue;
  comment: string | null;
}

export interface ChecklistTemplate {
  templateId: string;
  resourceType: ResourceType;
  items: Array<{
    itemKey: string;
    label: string;
    description: string | null;
    recommendation: string | null;
  }>;
}

export interface ChecklistTemplatesResponse {
  templates: Partial<Record<ResourceType, ChecklistTemplate>>;
}

export interface ResourceDetailResponse {
  resource: ResourceListItem;
  checklist: {
    templateId: string;
    resourceType: ResourceType;
    items: ChecklistItem[];
  };
  reviewSession: ReviewSession;
}

export interface ChecklistSaveRequest {
  responses: Array<{
    itemKey: string;
    value: ChecklistValue;
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
  resourceType: ResourceType;
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

export interface ReportResponse {
  jobId: string;
  generatedAt: string;
  summary: ReviewSummary;
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

export function getResourceTypeLabel(type: ResourceType): string {
  switch (type) {
    case 'WEB':
      return 'Web';
    case 'PDF':
      return 'PDF';
    case 'VIDEO':
      return 'Vídeo';
    case 'NOTEBOOK':
      return 'Notebook';
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
