import { AppMode, ChecklistDecision } from './types';

const COURSE_NAME_PREFIX = 'accessiblecourse.course-name';
const APP_MODE_KEY = 'accessiblecourse.app-mode';

export function classNames(
  ...values: Array<string | false | null | undefined>
) {
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
    return 'Generando diagnóstico';
  }

  if (progress >= 85) {
    return 'Procesando accesibilidad de los recursos HTML';
  }

  if (progress >= 75) {
    return 'Buscando descargables';
  }

  if (progress >= 50) {
    return 'Comprobando acceso';
  }

  if (progress >= 25) {
    return 'Detectando recursos';
  }

  return 'Leyendo estructura del curso';
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

export function isAppMode(value: string | null | undefined): value is AppMode {
  return value === 'online' || value === 'offline';
}

export function rememberAppMode(mode: AppMode) {
  if (typeof window === 'undefined') {
    return;
  }

  window.localStorage.setItem(APP_MODE_KEY, mode);
}

export function loadRememberedAppMode() {
  if (typeof window === 'undefined') {
    return null;
  }

  const storedMode = window.localStorage.getItem(APP_MODE_KEY);
  return isAppMode(storedMode) ? storedMode : null;
}

export function resolveAppMode(mode: string | null | undefined): AppMode {
  return isAppMode(mode) ? mode : (loadRememberedAppMode() ?? 'offline');
}

export function getModeSearch(mode: AppMode) {
  return `?mode=${mode}`;
}

export function getModeRoute(mode: AppMode) {
  const pathname = mode === 'online' ? '/online' : '/offline';
  return `${pathname}${getModeSearch(mode)}`;
}
