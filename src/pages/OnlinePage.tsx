import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';
import { api } from '../lib/api';
import type { CanvasAuth, OnlineCourse } from '../lib/types';
import { getModeSearch, rememberAppMode, rememberCourseName } from '../lib/utils';

function buildCourseLabel(course: OnlineCourse) {
  const meta = [course.term, course.startAt ? new Date(course.startAt).toLocaleDateString('es-ES') : null]
    .filter(Boolean)
    .join(' · ');

  return meta ? `${course.name} (${meta})` : course.name;
}

export function OnlinePage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [canvasBaseUrl, setCanvasBaseUrl] = useState('');
  const [canvasToken, setCanvasToken] = useState('');
  const [courses, setCourses] = useState<OnlineCourse[]>([]);
  const [selectedCourseId, setSelectedCourseId] = useState('');
  const [courseSearch, setCourseSearch] = useState('');
  const [isLoadingCourses, setIsLoadingCourses] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    rememberAppMode('online');

    if (searchParams.get('mode') !== 'online') {
      setSearchParams({ mode: 'online' }, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const filteredCourses = useMemo(() => {
    const normalizedQuery = courseSearch.trim().toLowerCase();
    if (!normalizedQuery) {
      return courses;
    }

    return courses.filter((course) =>
      `${course.name} ${course.term ?? ''}`.toLowerCase().includes(normalizedQuery),
    );
  }, [courseSearch, courses]);

  const selectedCourse =
    filteredCourses.find((course) => course.id === selectedCourseId) ??
    courses.find((course) => course.id === selectedCourseId) ??
    null;

  const canvasAuth: CanvasAuth | null =
    canvasBaseUrl.trim() && canvasToken.trim()
      ? {
          baseUrl: canvasBaseUrl.trim(),
          token: canvasToken.trim(),
          authMode: 'token',
        }
      : null;

  const handleLoadCourses = async () => {
    if (!canvasAuth) {
      setError('Introduce la URL base y el token de Canvas para cargar tus cursos.');
      return;
    }

    try {
      setIsLoadingCourses(true);
      setError(null);
      const nextCourses = await api.listOnlineCourses(canvasAuth);
      setCourses(nextCourses);
      setSelectedCourseId(nextCourses[0]?.id ?? '');
      setCourseSearch('');
      if (nextCourses.length === 0) {
        setError('No hemos encontrado cursos accesibles con ese usuario de Canvas.');
      }
    } catch (caughtError) {
      setError(
        caughtError instanceof Error ? caughtError.message : 'No hemos podido cargar los cursos.',
      );
    } finally {
      setIsLoadingCourses(false);
    }
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!canvasAuth) {
      setError('Introduce la URL base y el token de Canvas para continuar.');
      return;
    }

    if (!selectedCourse) {
      setError('Selecciona un curso de Canvas antes de empezar el análisis.');
      return;
    }

    try {
      setIsSubmitting(true);
      setError(null);
      const { jobId } = await api.createOnlineJob(
        {
          courseId: selectedCourse.id,
        },
        canvasAuth,
      );
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
      description="Conecta con Canvas/UOC, elige un curso accesible y genera el inventario directamente desde sus módulos."
      title="Conectar a Canvas/UOC"
    >
      <form className="card-panel mx-auto max-w-3xl space-y-6 p-6 sm:p-8" onSubmit={handleSubmit}>
        <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr_auto]">
          <div className="space-y-2">
            <label className="block text-sm font-semibold text-ink" htmlFor="canvas-base-url">
              Canvas Base URL
            </label>
            <input
              autoComplete="url"
              className="field-input"
              id="canvas-base-url"
              onChange={(event) => {
                setCanvasBaseUrl(event.target.value);
                setError(null);
              }}
              placeholder="https://tu-canvas/"
              type="url"
              value={canvasBaseUrl}
            />
          </div>

          <div className="space-y-2">
            <label className="block text-sm font-semibold text-ink" htmlFor="canvas-token">
              Token de Canvas
            </label>
            <input
              autoComplete="off"
              className="field-input"
              id="canvas-token"
              onChange={(event) => {
                setCanvasToken(event.target.value);
                setError(null);
              }}
              placeholder="Pega aquí tu token"
              type="password"
              value={canvasToken}
            />
          </div>

          <div className="flex items-end">
            <button
              className="button-secondary w-full lg:w-auto"
              disabled={!canvasAuth || isLoadingCourses}
              onClick={() => {
                void handleLoadCourses();
              }}
              type="button"
            >
              {isLoadingCourses ? 'Cargando…' : 'Cargar cursos'}
            </button>
          </div>
        </div>

        <p className="text-sm text-subtle">
          El token se usa solo para esta sesión y para el job que lances ahora; no se incluye en respuestas ni en logs.
        </p>

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)]">
          <div className="space-y-2">
            <label className="block text-sm font-semibold text-ink" htmlFor="course-search">
              Buscar curso
            </label>
            <input
              className="field-input"
              id="course-search"
              onChange={(event) => setCourseSearch(event.target.value)}
              placeholder="Filtra por nombre o periodo"
              type="search"
              value={courseSearch}
            />
          </div>

          <div className="space-y-2">
            <label className="block text-sm font-semibold text-ink" htmlFor="canvas-course">
              Curso de Canvas
            </label>
            <select
              className="field-input min-h-[13rem]"
              id="canvas-course"
              onChange={(event) => setSelectedCourseId(event.target.value)}
              size={Math.min(Math.max(filteredCourses.length, 1), 8)}
              value={selectedCourseId}
            >
              {filteredCourses.length === 0 ? (
                <option value="">No hay cursos para mostrar</option>
              ) : (
                filteredCourses.map((course) => (
                  <option key={course.id} value={course.id}>
                    {buildCourseLabel(course)}
                  </option>
                ))
              )}
            </select>
          </div>
        </div>

        {selectedCourse ? (
          <div className="rounded-2xl border border-line bg-[#f9faf7] p-4 text-sm text-subtle">
            <p>
              <span className="font-semibold text-ink">Curso:</span> {selectedCourse.name}
            </p>
            {selectedCourse.term ? (
              <p className="mt-1">
                <span className="font-semibold text-ink">Periodo:</span> {selectedCourse.term}
              </p>
            ) : null}
          </div>
        ) : null}

        {error ? (
          <p
            aria-live="assertive"
            className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-danger"
            role="alert"
          >
            {error}
          </p>
        ) : null}

        <button
          className="button-primary w-full"
          disabled={!selectedCourse || !canvasAuth || isSubmitting}
          type="submit"
        >
          {isSubmitting ? 'Preparando análisis…' : 'Analizar curso online'}
        </button>
      </form>
    </LayoutSimple>
  );
}
