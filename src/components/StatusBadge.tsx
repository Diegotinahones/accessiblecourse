import type { ResourceHealthStatus, ReviewSessionStatus, ReviewState } from '../lib/types';
import { getReviewStateLabel, getSessionStatusLabel } from '../lib/types';

type BadgeTone = 'success' | 'warning' | 'danger' | 'neutral';

interface BadgeProps {
  label: string;
  tone: BadgeTone;
}

function Badge({ label, tone }: BadgeProps) {
  return <span className={`status-badge status-badge--${tone}`}>{label}</span>;
}

export function ReviewStateBadge({ state }: { state: ReviewState }) {
  const tone: BadgeTone =
    state === 'OK' ? 'success' : state === 'NEEDS_FIX' ? 'danger' : 'warning';
  return <Badge label={getReviewStateLabel(state)} tone={tone} />;
}

export function SessionStatusBadge({ status }: { status: ReviewSessionStatus }) {
  const tone: BadgeTone =
    status === 'COMPLETE' ? 'success' : status === 'NOT_STARTED' ? 'neutral' : 'warning';
  return <Badge label={getSessionStatusLabel(status)} tone={tone} />;
}

export function InventoryStatusBadge({ status }: { status: ResourceHealthStatus }) {
  const tone: BadgeTone =
    status === 'OK' ? 'success' : status === 'ERROR' ? 'danger' : 'warning';
  return <Badge label={status} tone={tone} />;
}
