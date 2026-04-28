import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';
import { api } from '../lib/api';
import type { OnlineCourse } from '../lib/types';
import { getModeSearch, rememberAppMode, rememberCourseName } from '../lib/utils';

function buildCourseLabel(course: OnlineCourse) {
  return course.courseCode && course.courseCode !== course.name
    ? `${course.name} (${course.courseCode})`
    : course.name;
}

export function OnlinePage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [courses, setCourses] = useState<OnlineCourse[]>([]);
  const [selectedCourseId, setSelectedCourseId] = useState('');
  const [courseSearch, setCourseSearch] = useState('');
  const [isLoadingCourses, setIsLoadingCourses] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    rememberAppMode('online');

    if (searchParams.get('mode') !== 'online') {
      setSearchParams({ mode: 'online' }, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  async function loadCourses() {
    try {
      setIsLoadingCourses(true);
      setError(null);
      const nextCourses = await api.listCanvasCourses();
      setCourses(nextCourses);
      setSelectedCourseId((current) =>
        current && nextCourses.some((course) => course.id === current)
          ? current
          : nextCourses[0]?.id ?? '',
      );
      if (nextCourses.length === 0) {
        setError('No hemos encontrado cursos activos para este token de Canvas/UOC.');
      }
    } catch (caughtError) {
      setCourses([]);
      setSelectedCourseId('');
      setError(
        caughtError instanceof Error ? caughtError.message : 'No hemos podido cargar los cursos de Canvas/UOC.',
      );
    } finally {
      setIsLoadingCourses(false);
    }
  }

  useEffect(() => {
    let cancelled = false;

    async function loadInitialCourses() {
      try {
        setIsLoadingCourses(true);
        setError(null);
        const nextCourses = await api.listCanvasCourses();
        if (cancelled) {
          return;
        }
        setCourses(nextCourses);
        setSelectedCourseId(nextCourses[0]?.id ?? '');
        if (nextCourses.length === 0) {
          setError('No hemos encontrado cursos activos para este token de Canvas/UOC.');
        }
      } catch (caughtError) {
        if (!cancelled) {
          setCourses([]);
          setSelectedCourseId('');
          setError(
            caughtError instanceof Error
              ? caughtError.message
              : 'No hemos podido cargar los cursos de Canvas/UOC.',
          );
        }
      } finally {
        if (!cancelled) {
          setIsLoadingCourses(false);
        }
      }
    }

    void loadInitialCourses();

    return () => {
      cancelled = true;
    };
  }, []);

  const filteredCourses = useMemo(() => {
    const normalizedQuery = courseSearch.trim().toLowerCase();
    if (!normalizedQuery) {
      return courses;
    }

    return courses.filter((course) =>
      `${course.name} ${course.courseCode ?? ''} ${course.workflowState ?? ''}`
        .toLowerCase()
        .includes(normalizedQuery),
    );
  }, [courseSearch, courses]);

  const selectedCourse =
    filteredCourses.find((course) => course.id === selectedCourseId) ??
    courses.find((course) => course.id === selectedCourseId) ??
    null;

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!selectedCourse) {
      setError('Selecciona un curso de Canvas/UOC antes de empezar el análisis.');
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
      description="Elige uno de tus cursos activos de Canvas/UOC y genera el inventario directamente desde sus módulos."
      title="Online (UOC)"
    >
      <form className="card-panel mx-auto max-w-3xl space-y-6 p-6 sm:p-8" onSubmit={handleSubmit}>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-ink">Cursos disponibles</h2>
            <p className="mt-1 text-sm text-subtle">
              Se cargan desde Canvas/UOC usando el token seguro configurado en Railway.
            </p>
          </div>

          <button
            className="button-secondary w-full sm:w-auto"
            disabled={isLoadingCourses}
            onClick={() => {
              void loadCourses();
            }}
            type="button"
          >
            {isLoadingCourses ? 'Cargando…' : 'Recargar cursos'}
          </button>
        </div>

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)]">
          <div className="space-y-2">
            <label className="block text-sm font-semibold text-ink" htmlFor="course-search">
              Buscar curso
            </label>
            <input
              className="field-input"
              disabled={isLoadingCourses || courses.length === 0}
              id="course-search"
              onChange={(event) => setCourseSearch(event.target.value)}
              placeholder="Filtra por nombre o código"
              type="search"
              value={courseSearch}
            />
          </div>

          <div className="space-y-2">
            <label className="block text-sm font-semibold text-ink" htmlFor="canvas-course">
              Curso de Canvas/UOC
            </label>
            <select
              className="field-input min-h-[13rem]"
              disabled={isLoadingCourses || filteredCourses.length === 0}
              id="canvas-course"
              onChange={(event) => setSelectedCourseId(event.target.value)}
              size={Math.min(Math.max(filteredCourses.length, 1), 8)}
              value={selectedCourseId}
            >
              {isLoadingCourses ? (
                <option value="">Cargando cursos…</option>
              ) : filteredCourses.length === 0 ? (
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
            {selectedCourse.courseCode ? (
              <p className="mt-1">
                <span className="font-semibold text-ink">Código:</span> {selectedCourse.courseCode}
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
          disabled={!selectedCourse || isLoadingCourses || isSubmitting}
          type="submit"
        >
          {isSubmitting ? 'Preparando análisis…' : 'Analizar curso online'}
        </button>
      </form>
    </LayoutSimple>
  );
}
