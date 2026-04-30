import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';
import { api } from '../lib/api';
import type { OnlineCourse } from '../lib/types';
import { getModeSearch, rememberAppMode, rememberCourseName } from '../lib/utils';

function buildCourseMeta(course: OnlineCourse) {
  return [course.courseCode, course.term].filter(Boolean).join(' · ');
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
        setError('No hemos encontrado cursos activos para este acceso de Canvas/UOC.');
      }
    } catch (caughtError) {
      setCourses([]);
      setSelectedCourseId('');
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : 'No hemos podido cargar los cursos de Canvas/UOC.',
      );
    } finally {
      setIsLoadingCourses(false);
    }
  }

  useEffect(() => {
    void loadCourses();
  }, []);

  const filteredCourses = useMemo(() => {
    const normalizedQuery = courseSearch.trim().toLowerCase();
    if (!normalizedQuery) {
      return courses;
    }

    return courses.filter((course) =>
      `${course.name} ${course.courseCode ?? ''} ${course.term ?? ''}`
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
      description="Selecciona el curso de Canvas/UOC que quieres analizar."
      title="Selecciona un curso"
    >
      <form
        className="card-panel mx-auto max-w-3xl space-y-6 p-6 sm:p-8"
        onSubmit={handleSubmit}
      >
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div className="space-y-1">
            <h2 className="text-lg font-semibold text-ink">Cursos disponibles</h2>
            <p className="text-sm text-subtle">
              Se cargan desde Canvas/UOC usando la configuración segura del backend.
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

        <div className="space-y-2">
          <label className="block text-sm font-semibold text-ink" htmlFor="course-search">
            Buscar curso
          </label>
          <input
            className="field-input"
            disabled={isLoadingCourses || courses.length === 0}
            id="course-search"
            onChange={(event) => setCourseSearch(event.target.value)}
            placeholder="Filtra por nombre, código o periodo"
            type="search"
            value={courseSearch}
          />
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

        <fieldset className="space-y-4">
          <legend className="text-base font-semibold text-ink">Curso de Canvas/UOC</legend>

          {isLoadingCourses ? (
            <p className="rounded-2xl border border-line bg-[#f7faf7] px-4 py-4 text-sm text-subtle">
              Cargando cursos…
            </p>
          ) : filteredCourses.length === 0 ? (
            <p className="rounded-2xl border border-line bg-[#f7faf7] px-4 py-4 text-sm text-subtle">
              No hay cursos para mostrar con el filtro actual.
            </p>
          ) : (
            <div className="space-y-3">
              {filteredCourses.map((course) => {
                const meta = buildCourseMeta(course);
                const descriptionId = `course-${course.id}-description`;
                const checked = selectedCourseId === course.id;

                return (
                  <label
                    key={course.id}
                    className={`block cursor-pointer rounded-3xl border p-5 transition ${
                      checked
                        ? 'border-ink bg-[#f7faf7]'
                        : 'border-line bg-white hover:border-[#9cb3a2]'
                    }`}
                  >
                    <div className="flex items-start gap-4">
                      <input
                        aria-describedby={meta ? descriptionId : undefined}
                        checked={checked}
                        className="mt-1 h-5 w-5 accent-[#205e3c]"
                        name="canvas-course"
                        onChange={() => setSelectedCourseId(course.id)}
                        type="radio"
                        value={course.id}
                      />

                      <div className="space-y-1">
                        <p className="text-base font-semibold text-ink">{course.name}</p>
                        {meta ? (
                          <p className="text-sm text-subtle" id={descriptionId}>
                            {meta}
                          </p>
                        ) : null}
                      </div>
                    </div>
                  </label>
                );
              })}
            </div>
          )}
        </fieldset>

        <button
          className="button-primary w-full sm:w-auto"
          disabled={!selectedCourse || isSubmitting || isLoadingCourses}
          type="submit"
        >
          {isSubmitting ? 'Preparando análisis…' : 'Continuar'}
        </button>
      </form>
    </LayoutSimple>
  );
}
