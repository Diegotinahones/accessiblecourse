import {
  ResourceState,
  ReviewResourceHealthStatus,
  ReviewSessionStatus,
  ReviewState,
  getReviewStateLabel,
  getSessionStatusLabel,
} from '../lib/types';
import { classNames } from '../lib/utils';

interface StatusBadgeProps {
  status: ResourceState;
}

const statusStyles: Record<ResourceState, string> = {
  OK: 'border-emerald-200 bg-emerald-50 text-success',
  AVISO: 'border-amber-200 bg-amber-50 text-warning',
  ERROR: 'border-rose-200 bg-rose-50 text-danger',
};

export function StatusBadge({ status }: StatusBadgeProps) {
  return (
    <span
      aria-label={`Estado ${status}`}
      className={classNames(
        'inline-flex rounded-full border px-3 py-1 text-sm font-semibold',
        statusStyles[status],
      )}
    >
      {status}
    </span>
  );
}

interface InventoryStatusBadgeProps {
  status: ReviewResourceHealthStatus;
}

interface ReviewStateBadgeProps {
  state: ReviewState;
}

interface SessionStatusBadgeProps {
  status: ReviewSessionStatus;
}

const inventoryStatusStyles: Record<ReviewResourceHealthStatus, string> = {
  OK: 'border-emerald-200 bg-emerald-50 text-success',
  WARN: 'border-amber-200 bg-amber-50 text-warning',
  ERROR: 'border-rose-200 bg-rose-50 text-danger',
};

const reviewStateStyles: Record<ReviewState, string> = {
  OK: 'border-emerald-200 bg-emerald-50 text-success',
  IN_REVIEW: 'border-sky-200 bg-sky-50 text-sky-700',
  NEEDS_FIX: 'border-rose-200 bg-rose-50 text-danger',
};

const sessionStatusStyles: Record<ReviewSessionStatus, string> = {
  NOT_STARTED: 'border-slate-200 bg-slate-50 text-slate-600',
  IN_PROGRESS: 'border-sky-200 bg-sky-50 text-sky-700',
  COMPLETE: 'border-emerald-200 bg-emerald-50 text-success',
};

export function InventoryStatusBadge({ status }: InventoryStatusBadgeProps) {
  return (
    <span
      aria-label={`Estado del inventario ${status}`}
      className={classNames(
        'inline-flex rounded-full border px-3 py-1 text-sm font-semibold',
        inventoryStatusStyles[status],
      )}
    >
      {status}
    </span>
  );
}

export function ReviewStateBadge({ state }: ReviewStateBadgeProps) {
  return (
    <span
      aria-label={`Estado de revision ${getReviewStateLabel(state)}`}
      className={classNames(
        'inline-flex rounded-full border px-3 py-1 text-sm font-semibold',
        reviewStateStyles[state],
      )}
    >
      {getReviewStateLabel(state)}
    </span>
  );
}

export function SessionStatusBadge({ status }: SessionStatusBadgeProps) {
  return (
    <span
      aria-label={`Estado de sesion ${getSessionStatusLabel(status)}`}
      className={classNames(
        'inline-flex rounded-full border px-3 py-1 text-sm font-semibold',
        sessionStatusStyles[status],
      )}
    >
      {getSessionStatusLabel(status)}
    </span>
  );
}
