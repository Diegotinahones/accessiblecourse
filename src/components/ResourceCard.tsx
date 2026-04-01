import { useEffect, useState } from 'react';
import { loadResourceChecklist, saveResourceChecklist } from '../lib/checklistStorage';
import { Resource, ResourceChecklistState } from '../lib/types';
import { Checklist } from './Checklist';
import { StatusBadge } from './StatusBadge';

interface ResourceCardProps {
  jobId: string;
  resource: Resource;
  checklistState: ResourceChecklistState;
  onChecklistChange: (resourceId: string, state: ResourceChecklistState) => void;
}

export function ResourceCard({ jobId, resource, checklistState, onChecklistChange }: ResourceCardProps) {
  const [expanded, setExpanded] = useState(false);
  const regionId = `detalle-${resource.id}`;
  const buttonId = `trigger-${resource.id}`;

  useEffect(() => {
    if (Object.keys(checklistState).length === 0) {
      const persistedState = loadResourceChecklist(jobId, resource);
      onChecklistChange(resource.id, persistedState);
    }
  }, [checklistState, jobId, onChecklistChange, resource]);

  const handleChecklistChange = (nextState: ResourceChecklistState) => {
    saveResourceChecklist(jobId, resource.id, nextState);
    onChecklistChange(resource.id, nextState);
  };

  return (
    <article className="card-panel overflow-hidden">
      <div className="flex flex-col gap-6 p-6 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-4">
          <div className="space-y-2">
            <h2 className="text-2xl font-semibold text-ink">{resource.title}</h2>
            <div className="flex flex-wrap gap-3 text-sm text-subtle">
              <span className="rounded-full bg-slate-100 px-3 py-1 font-medium text-ink">
                Tipo: {resource.type}
              </span>
              <span className="rounded-full bg-slate-100 px-3 py-1 font-medium text-ink">
                Origen: {resource.origin}
              </span>
            </div>
          </div>

          <StatusBadge status={resource.status} />
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
            onChange={handleChecklistChange}
            resourceId={resource.id}
            resourceType={resource.type}
            value={checklistState}
          />
        </div>
      ) : null}
    </article>
  );
}
