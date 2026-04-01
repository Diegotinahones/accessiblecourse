import { useEffect, useId, useState } from 'react';
import { getChecklistTemplate } from '../lib/checklistCatalog';
import { ChecklistDecision, ResourceChecklistState, ResourceType } from '../lib/types';
import { classNames, getDecisionLabel } from '../lib/utils';

interface ChecklistProps {
  resourceId: string;
  resourceType: ResourceType;
  value: ResourceChecklistState;
  disabled?: boolean;
  onChange: (nextState: ResourceChecklistState) => void;
}

const decisionOptions: Array<{ value: ChecklistDecision; label: string }> = [
  { value: 'pending', label: 'Pendiente' },
  { value: 'pass', label: 'Cumple' },
  { value: 'fail', label: 'No cumple' },
];

export function Checklist({ resourceId, resourceType, value, disabled = false, onChange }: ChecklistProps) {
  const fallbackId = useId();
  const [state, setState] = useState<ResourceChecklistState>(value);
  const items = getChecklistTemplate(resourceType);

  useEffect(() => {
    setState(value);
  }, [value]);

  const handleChange = (itemId: string, decision: ChecklistDecision) => {
    const nextState = {
      ...state,
      [itemId]: decision,
    };
    setState(nextState);
    onChange(nextState);
  };

  return (
    <div className="space-y-5">
      <p className="text-sm text-subtle">Marca el estado actual de cada punto del checklist para este recurso.</p>

      <ul className="space-y-4" role="list">
        {items.map((item) => {
          const currentValue = state[item.id] ?? 'pending';
          const groupName = `${resourceId}-${item.id}-${fallbackId}`;

          return (
            <li key={item.id} className="rounded-2xl border border-slate-200 bg-panel p-5">
              <fieldset className="space-y-4" disabled={disabled}>
                <legend className="text-base font-semibold text-ink">{item.label}</legend>
                <p className="text-sm text-subtle">
                  Estado actual: <strong className="text-ink">{getDecisionLabel(currentValue)}</strong>
                </p>
                <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
                  {decisionOptions.map((option) => (
                    <label
                      key={option.value}
                      className={classNames(
                        'flex min-w-[11rem] cursor-pointer items-center gap-3 rounded-xl border px-4 py-3 text-sm font-medium transition',
                        currentValue === option.value
                          ? 'border-ink bg-white text-ink'
                          : 'border-line bg-white text-subtle hover:border-slate-300',
                        disabled && 'cursor-not-allowed opacity-70',
                      )}
                    >
                      <input
                        checked={currentValue === option.value}
                        className="h-4 w-4 accent-ink"
                        name={groupName}
                        onChange={() => handleChange(item.id, option.value)}
                        type="radio"
                        value={option.value}
                      />
                      <span>{option.label}</span>
                    </label>
                  ))}
                </div>
              </fieldset>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
