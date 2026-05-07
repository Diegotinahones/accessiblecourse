import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';
import { ApiError, api } from '../lib/api';
import type { OnlineCourse } from '../lib/types';
import {
  getModeSearch,
  rememberAppMode,
  rememberCourseName,
} from '../lib/utils';

function buildCourseMeta(course: OnlineCourse) {
  const uniqueParts = [course.courseCode, course.term].filter(
    (part, index, parts): part is string =>
      Boolean(part) && parts.indexOf(part) === index && part !== course.name,
  );

  return uniqueParts.join(' · ');
}

function getCourseLoadErrorMessage(caughtError: unknown) {
  if (
    caughtError instanceof ApiError &&
    (caughtError.status === 401 || caughtError.status === 403)
  ) {
    return 'No hemos podido conectar con Canvas/UOC. Revisa la configuración o el token de acceso.';
  }

  return caughtError instanceof Error
    ? caughtError.message
    : 'No hemos podido cargar los cursos de Canvas/UOC.';
}

export function OnlinePage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [courses, setCourses] = useState<OnlineCourse[]>([]);
  const [selectedCourseId, setSelectedCourseId] = useState('');
  const [hasLoadedCourses, setHasLoadedCourses] = useState(false);
  const [isLoadingCourses, setIsLoadingCourses] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hasRequestedCoursesRef = useRef(false);

  useEffect(() => {
    rememberAppMode('online');

    if (searchParams.get('mode') !== 'online') {
      setSearchParams({ mode: 'online' }, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const loadCourses = useCallback(async () => {
    try {
      setIsLoadingCourses(true);
      setHasLoadedCourses(true);
      setError(null);
      const nextCourses = await api.listCanvasCourses();
      setCourses(nextCourses);
      setSelectedCourseId((current) =>
        current && nextCourses.some((course) => course.id === current)
          ? current
          : (nextCourses[0]?.id ?? ''),
      );

      setError(null);
    } catch (caughtError) {
      setCourses([]);
      setSelectedCourseId('');
      setError(getCourseLoadErrorMessage(caughtError));
    } finally {
      setIsLoadingCourses(false);
    }
  }, []);

  useEffect(() => {
    if (hasRequestedCoursesRef.current) {
      return;
    }

    hasRequestedCoursesRef.current = true;
    void loadCourses();
  }, [loadCourses]);

  const selectedCourse =
    courses.find((course) => course.id === selectedCourseId) ?? null;
  const shouldUseSelect = courses.length > 8;

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!selectedCourse) {
      setError('Selecciona un curso antes de empezar el análisis.');
      return;
    }

    try {
      setIsSubmitting(true);
      setError(null);
      const { jobId } = await api.createCanvasJob({
        courseId: selectedCourse.id,
        courseName: selectedCourse.name,
      });
      rememberAppMode('online');
      rememberCourseName(jobId, selectedCourse.name);
      navigate(`/analyzing/${jobId}${getModeSearch('online')}`);
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : 'No hemos podido preparar el análisis online.',
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <LayoutSimple
      align="center"
      backLabel="Cambiar modo"
      backTo="/?mode=online"
      showTokenButton={false}
      title="Cursos disponibles"
      useMainLandmark={false}
    >
      <form
        className="mx-auto max-w-3xl space-y-6 rounded-2xl border border-line bg-white p-6 shadow-card sm:p-8"
        onSubmit={handleSubmit}
      >
        <div className="flex justify-end">
          {error ? (
            <button
              className="button-secondary w-full sm:w-auto"
              disabled={isLoadingCourses}
              onClick={() => {
                void loadCourses();
              }}
              type="button"
            >
              {isLoadingCourses ? 'Reintentando…' : 'Reintentar carga'}
            </button>
          ) : null}
        </div>

        {error ? (
          <p
            aria-live="assertive"
            className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-danger"
            role="alert"
          >
            {error}
          </p>
        ) : null}

        <div className="space-y-4 text-left">
          {!hasLoadedCourses && !isLoadingCourses ? (
            <p className="rounded-2xl border border-line bg-[var(--color-surface-soft)] px-4 py-4 text-sm leading-6 text-subtle">
              Estamos consultando Canvas/UOC automáticamente.
            </p>
          ) : null}

          {isLoadingCourses ? (
            <p
              className="rounded-2xl border border-line bg-[var(--color-surface-soft)] px-4 py-4 text-sm leading-6 text-subtle"
              role="status"
            >
              Cargando cursos…
            </p>
          ) : null}

          {hasLoadedCourses && !isLoadingCourses && courses.length === 0 ? (
            <p
              className="rounded-2xl border border-line bg-[var(--color-surface-soft)] px-4 py-4 text-sm leading-6 text-subtle"
              role="status"
            >
              No hay cursos disponibles. Revisa la configuración de Canvas/UOC o
              vuelve a intentarlo.
            </p>
          ) : null}

          {hasLoadedCourses && !isLoadingCourses && courses.length > 0 ? (
            shouldUseSelect ? (
              <div className="space-y-2">
                <label
                  className="block text-sm font-semibold text-ink"
                  htmlFor="canvas-course-select"
                >
                  Curso de Canvas/UOC
                </label>
                <select
                  className="field-input"
                  id="canvas-course-select"
                  onChange={(event) => setSelectedCourseId(event.target.value)}
                  value={selectedCourseId}
                >
                  {courses.map((course) => {
                    const meta = buildCourseMeta(course);
                    return (
                      <option key={course.id} value={course.id}>
                        {meta ? `${course.name} · ${meta}` : course.name}
                      </option>
                    );
                  })}
                </select>
              </div>
            ) : (
              <fieldset className="space-y-4">
                <legend className="sr-only">Curso de Canvas/UOC</legend>

                <div className="space-y-3">
                  {courses.map((course) => {
                    const meta = buildCourseMeta(course);
                    const inputId = `course-${course.id}`;
                    const descriptionId = `course-${course.id}-description`;
                    const checked = selectedCourseId === course.id;

                    return (
                      <label
                        key={course.id}
                        className={`choice-panel block cursor-pointer ${
                          checked ? 'choice-panel-selected' : ''
                        }`}
                        htmlFor={inputId}
                      >
                        <span className="flex items-start gap-4">
                          <input
                            checked={checked}
                            className="mt-1 h-5 w-5 shrink-0 accent-[var(--uoc-blue)]"
                            id={inputId}
                            name="canvas-course"
                            onChange={() => setSelectedCourseId(course.id)}
                            type="radio"
                            value={course.id}
                          />

                          <span className="space-y-1">
                            <span className="block text-base font-semibold text-ink">
                              {course.name}
                            </span>
                            {meta ? (
                              <span
                                aria-hidden="true"
                                className="block text-sm text-subtle"
                                id={descriptionId}
                              >
                                {meta}
                              </span>
                            ) : null}
                          </span>
                        </span>
                      </label>
                    );
                  })}
                </div>
              </fieldset>
            )
          ) : null}
        </div>

        <button
          className="button-primary w-full sm:w-auto"
          disabled={!selectedCourse || isSubmitting || isLoadingCourses}
          type="submit"
        >
          {isSubmitting ? 'Preparando análisis…' : 'Analizar curso'}
        </button>
      </form>
    </LayoutSimple>
  );
}
