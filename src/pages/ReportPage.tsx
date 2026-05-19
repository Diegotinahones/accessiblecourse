import { useEffect, useState } from 'react';
import { useLocation, useParams, useSearchParams } from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';
import {
  ApiError,
  api,
  fetchAccessibility,
  fetchReport,
  fetchResources,
  fetchSummary,
  generateReport,
  getDirectReportDownloadUrls,
} from '../lib/api';
import type {
  AccessibilityResponse,
  AppMode,
  GeneratedReport,
  JobStatus,
  ResourceListResponse,
  ReviewSummary,
} from '../lib/types';
import {
  getModeSearch,
  isAppMode,
  loadRememberedAppMode,
  rememberAppMode,
} from '../lib/utils';

interface ReportLocationState {
  courseName?: string | null;
}

function getLoadMessage(isGenerating: boolean) {
  return isGenerating ? 'Generando informe…' : 'Cargando informe…';
}

function downloadFile(url: string) {
  window.location.assign(url);
}

function normalizeCourseTitleCandidate(value: string | null | undefined) {
  const trimmedValue = value?.trim();
  return trimmedValue || null;
}

function isLikelyCompleteCourseTitle(value: string) {
  return (
    value.length > 8 &&
    (value.includes(' - ') ||
      value.includes(' – ') ||
      value.includes(' — ') ||
      /\s/.test(value))
  );
}

function isLikelyAbbreviatedCourseTitle(value: string) {
  return value.length <= 8 && !/\s/.test(value);
}

function resolveReportCourseTitle({
  access,
  accessibility,
  executiveSummary,
  job,
  navigationCourseName,
}: {
  access: ResourceListResponse | null;
  accessibility: AccessibilityResponse | null;
  executiveSummary: ReviewSummary | null;
  job: JobStatus | null;
  navigationCourseName: string | null | undefined;
}) {
  const candidates = [
    executiveSummary?.courseTitle,
    executiveSummary?.courseName,
    access?.courseTitle,
    access?.courseName,
    accessibility?.courseTitle,
    accessibility?.courseName,
    job?.courseTitle,
    navigationCourseName,
  ]
    .map(normalizeCourseTitleCandidate)
    .filter((candidate): candidate is string => Boolean(candidate));
  const completeCandidate = candidates.find(isLikelyCompleteCourseTitle);
  const firstCandidate = candidates[0];

  if (completeCandidate) {
    return completeCandidate;
  }

  if (firstCandidate && isLikelyAbbreviatedCourseTitle(firstCandidate)) {
    const longerCandidate = candidates.find(
      (candidate) => candidate.length > firstCandidate.length,
    );

    if (longerCandidate) {
      return longerCandidate;
    }
  }

  return firstCandidate ?? 'Curso analizado';
}

export function ReportPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const navigationState =
    (location.state as ReportLocationState | null) ?? null;
  const [report, setReport] = useState<GeneratedReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [access, setAccess] = useState<ResourceListResponse | null>(null);
  const [accessibility, setAccessibility] =
    useState<AccessibilityResponse | null>(null);
  const [executiveSummary, setExecutiveSummary] =
    useState<ReviewSummary | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);
  const modeParam = searchParams.get('mode');
  const appMode: AppMode = isAppMode(modeParam)
    ? modeParam
    : (loadRememberedAppMode() ?? 'offline');

  useEffect(() => {
    rememberAppMode(appMode);
  }, [appMode]);

  useEffect(() => {
    const reportJobId = jobId;

    if (!reportJobId) {
      setError('Falta el identificador del informe.');
      setLoading(false);
      return;
    }

    const resolvedJobId: string = reportJobId;
    let cancelled = false;

    async function loadOrGenerateReport() {
      setLoading(true);
      setError(null);

      try {
        const payload = await fetchReport(resolvedJobId);
        if (!cancelled) {
          setReport(payload);
        }
      } catch (loadError) {
        if (cancelled) {
          return;
        }

        if (loadError instanceof ApiError && loadError.status === 404) {
          try {
            setIsGenerating(true);
            const payload = await generateReport(resolvedJobId);
            if (!cancelled) {
              setReport(payload);
            }
          } catch (generationError) {
            if (!cancelled) {
              setError(
                generationError instanceof Error
                  ? generationError.message
                  : 'No se pudo generar el informe.',
              );
            }
          } finally {
            if (!cancelled) {
              setIsGenerating(false);
            }
          }

          return;
        }

        setError(
          loadError instanceof Error
            ? loadError.message
            : 'No se pudo cargar el informe.',
        );
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadOrGenerateReport();

    return () => {
      cancelled = true;
    };
  }, [jobId]);

  useEffect(() => {
    if (!jobId) {
      return;
    }

    const resolvedJobId = jobId;
    let cancelled = false;

    async function loadCourseTitleSources() {
      try {
        const summaryPayload = await fetchSummary(resolvedJobId);
        if (!cancelled) {
          setExecutiveSummary(summaryPayload);
        }
      } catch {
        if (!cancelled) {
          setExecutiveSummary(null);
        }
      }

      try {
        const accessPayload = await fetchResources(resolvedJobId);
        if (!cancelled) {
          setAccess(accessPayload);
        }
      } catch {
        if (!cancelled) {
          setAccess(null);
        }
      }

      try {
        const accessibilityPayload = await fetchAccessibility(resolvedJobId);
        if (!cancelled) {
          setAccessibility(accessibilityPayload);
        }
      } catch {
        if (!cancelled) {
          setAccessibility(null);
        }
      }

      try {
        const jobPayload = await api.getJobStatus(resolvedJobId);
        if (!cancelled) {
          setJob(jobPayload);
        }
      } catch {
        if (!cancelled) {
          setJob(null);
        }
      }
    }

    void loadCourseTitleSources();

    return () => {
      cancelled = true;
    };
  }, [jobId]);

  const courseName = resolveReportCourseTitle({
    access,
    accessibility,
    executiveSummary,
    job,
    navigationCourseName: navigationState?.courseName,
  });

  useEffect(() => {
    if (!import.meta.env.DEV) {
      return;
    }

    console.debug('[AccessibleCourse] report course title fields', {
      access: {
        courseName: access?.courseName,
        courseTitle: access?.courseTitle,
      },
      accessibility: {
        courseName: accessibility?.courseName,
        courseTitle: accessibility?.courseTitle,
      },
      executiveSummary: {
        courseName: executiveSummary?.courseName,
        courseTitle: executiveSummary?.courseTitle,
      },
      job: {
        courseName: job?.courseName,
        courseTitle: job?.courseTitle,
      },
      navigationCourseName: navigationState?.courseName,
      resolvedCourseTitle: courseName,
    });
  }, [
    access,
    accessibility,
    courseName,
    executiveSummary,
    job,
    navigationState?.courseName,
  ]);

  const downloadUrls = jobId ? getDirectReportDownloadUrls(jobId) : null;

  return (
    <LayoutSimple
      backLabel="Volver a recursos"
      backTo={jobId ? `/resources/${jobId}${getModeSearch(appMode)}` : '/'}
      showTokenButton={false}
      title="Informe detallado"
      useMainLandmark={false}
    >
      {error ? (
        <div
          aria-live="assertive"
          className="rounded-2xl border border-rose-200 bg-rose-50 p-5 text-danger"
          role="alert"
        >
          {error}
        </div>
      ) : null}

      {loading ? (
        <section className="card-panel p-6 text-sm text-subtle">
          {getLoadMessage(isGenerating)}
        </section>
      ) : null}

      {!loading && report && downloadUrls ? (
        <section className="mx-auto max-w-3xl rounded-3xl border border-line bg-white p-6 shadow-card sm:p-8">
          <div className="space-y-3">
            <p className="text-sm font-semibold uppercase tracking-[0.12em] text-subtle">
              {courseName}
            </p>
            <p className="text-lg leading-8 text-ink">
              El informe incluye el diagnóstico completo por recurso, con
              incidencias ordenadas por gravedad, evidencias y recomendaciones
              de mejora.
            </p>
          </div>

          <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:flex-wrap">
            <button
              className="button-primary w-full sm:w-auto"
              onClick={() => downloadFile(downloadUrls.pdf)}
              type="button"
            >
              Descargar PDF
            </button>
            <button
              className="button-secondary w-full sm:w-auto"
              onClick={() => downloadFile(downloadUrls.docx)}
              type="button"
            >
              Descargar Word
            </button>
            <button
              className="button-secondary w-full sm:w-auto"
              onClick={() => downloadFile(downloadUrls.json)}
              type="button"
            >
              Descargar JSON
            </button>
          </div>
        </section>
      ) : null}
    </LayoutSimple>
  );
}
