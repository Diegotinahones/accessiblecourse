import { useState } from 'react';
import { Resource, ResourceChecklistState } from '../lib/types';
import { Checklist } from './Checklist';
import { StatusBadge } from './StatusBadge';

interface ResourceCardProps {
  resource: Resource;
  checklistState: ResourceChecklistState;
  isSaving?: boolean;
  onChecklistChange: (resourceId: string, state: ResourceChecklistState) => void;
}

export function ResourceCard({ resource, checklistState, isSaving = false, onChecklistChange }: ResourceCardProps) {
  const [expanded, setExpanded] = useState(false);
  const regionId = `detalle-${resource.id}`;
  const buttonId = `trigger-${resource.id}`;

  return (
    <article className="card-panel overflow-hidden">
      <div className="flex flex-col gap-6 p-6 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-4">
          <div className="space-y-2">
            <h2 className="text-2xl font-semibold text-ink">{resource.title}</h2>
            <div className="flex flex-wrap gap-3 text-sm text-subtle">
              <span className="rounded-full bg-slate-100 px-3 py-1 font-medium text-ink">Tipo: {resource.type}</span>
              <span className="rounded-full bg-slate-100 px-3 py-1 font-medium text-ink">Origen: {resource.origin}</span>
            </div>
            {resource.href ? <p className="max-w-2xl break-all text-sm text-subtle">Ruta: {resource.href}</p> : null}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <StatusBadge status={resource.status} />
            {isSaving ? <span className="text-sm text-subtle">Guardando checklist...</span> : null}
          </div>
        </div>

        <div className="sm:self-center">
          <button
            aria-controls={regionId}
            aria-expanded={expanded}
            className="button-secondary w-full sm:w-auto"
            id={buttonId}
            onClick={() => setExpanded((currentValue) => !currentValue)}
            type="button"
          >
            {expanded ? 'Ocultar detalle' : 'Ver detalle'}
          </button>
        </div>
      </div>

      {expanded ? (
        <div
          aria-labelledby={buttonId}
          className="border-t border-slate-200 bg-white px-6 py-6"
          id={regionId}
          role="region"
        >
          <Checklist
            disabled={isSaving}
            onChange={(nextState) => onChecklistChange(resource.id, nextState)}
            resourceId={resource.id}
            resourceType={resource.type}
            value={checklistState}
          />
        </div>
      ) : null}
    </article>
  );
}
