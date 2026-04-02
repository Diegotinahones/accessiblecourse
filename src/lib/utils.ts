import { ChecklistDecision } from './types';

const COURSE_NAME_PREFIX = 'accessiblecourse.course-name';

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
    return 'Generando inventario';
  }

  if (progress >= 50) {
    return 'Resolviendo recursos';
  }

  if (progress >= 25) {
    return 'Parseando estructura';
  }

  return 'Descomprimiendo paquete';
}

export function getCourseNameFromFilename(filename: string) {
  return filename.replace(/\.[^/.]+$/, '').trim() || 'Curso sin título';
}

export function rememberCourseName(jobId: string, filename: string) {
  if (typeof window === 'undefined') {
    return;
  }

  window.sessionStorage.setItem(
    `${COURSE_NAME_PREFIX}.${jobId}`,
    getCourseNameFromFilename(filename),
  );
}

export function loadRememberedCourseName(jobId: string) {
  if (typeof window === 'undefined') {
    return null;
  }

  return window.sessionStorage.getItem(`${COURSE_NAME_PREFIX}.${jobId}`);
}
