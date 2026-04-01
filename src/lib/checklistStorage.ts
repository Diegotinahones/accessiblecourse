import { getChecklistTemplate } from './checklistCatalog';
import { ChecklistState, Resource, ResourceChecklistState } from './types';

const CHECKLIST_PREFIX = 'accessible-course.checklist';

function getChecklistKey(jobId: string, resourceId: string) {
  return `${CHECKLIST_PREFIX}.${jobId}.${resourceId}`;
}

function getDefaultState(resource: Resource): ResourceChecklistState {
  return getChecklistTemplate(resource.type).reduce<ResourceChecklistState>((accumulator, item) => {
    accumulator[item.id] = 'pending';
    return accumulator;
  }, {});
}

export function loadResourceChecklist(jobId: string, resource: Resource): ResourceChecklistState {
  try {
    const rawValue = window.localStorage.getItem(getChecklistKey(jobId, resource.id));
    if (!rawValue) {
      return getDefaultState(resource);
    }

    const parsed = JSON.parse(rawValue) as ResourceChecklistState;
    return { ...getDefaultState(resource), ...parsed };
  } catch {
    return getDefaultState(resource);
  }
}

export function saveResourceChecklist(jobId: string, resourceId: string, state: ResourceChecklistState) {
  window.localStorage.setItem(getChecklistKey(jobId, resourceId), JSON.stringify(state));
}

export function loadJobChecklistState(jobId: string, resources: Resource[]): ChecklistState {
  return resources.reduce<ChecklistState>((accumulator, resource) => {
    accumulator[resource.id] = loadResourceChecklist(jobId, resource);
    return accumulator;
  }, {});
}
