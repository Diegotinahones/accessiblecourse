import { ChecklistDecision } from './types';

export function classNames(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(' ');
}

export function formatFileSize(size: number) {
  if (size < 1024) {
    return `${size} B`;
  }

  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }

  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export function getDecisionLabel(decision: ChecklistDecision) {
  if (decision === 'pass') {
    return 'Cumple';
  }

  if (decision === 'fail') {
    return 'No cumple';
  }

  return 'Pendiente';
}

export function buildStepMessage(progress: number) {
  if (progress >= 100) {
    return 'Analisis completado';
  }

  if (progress >= 75) {
    return 'Preparando checklist de recursos';
  }

  if (progress >= 50) {
    return 'Revisando accesibilidad base';
  }

  if (progress >= 25) {
    return 'Extrayendo recursos del curso';
  }

  return 'Validando archivo del curso';
}
