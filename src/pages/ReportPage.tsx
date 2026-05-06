import { useEffect, useState } from 'react';
import { useLocation, useParams, useSearchParams } from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';
import {
  ApiError,
  fetchReport,
  generateReport,
  getDirectReportDownloadUrls,
} from '../lib/api';
import type { AppMode, GeneratedReport } from '../lib/types';
import { formatDate } from '../lib/types';
import {
  classNames,
  getModeSearch,
  isAppMode,
  loadRememberedAppMode,
  loadRememberedCourseName,
  rememberAppMode,
} from '../lib/utils';

interface ReportLocationState {
  announcement?: string;
  courseName?: string | null;
}

function getLoadMessage(isGenerating: boolean) {
  return isGenerating ? 'Generando informe…' : 'Cargando informe…';
}

function getReportScore(report: GeneratedReport) {
  if (report.resourceCount === 0) {
    return 0;
  }

  const penalty = Math.min(
    100,
    Math.round((report.failedItemCount / report.resourceCount) * 10),
  );

  return Math.max(0, 100 - penalty);
}

function getScoreClass(score: number) {
  if (score >= 80) {
    return 'score-green';
  }

  if (score >= 60) {
    return 'score-yellow';
  }

  return 'score-red';
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
  const [announcement, setAnnouncement] = useState(
    navigationState?.announcement ?? '',
  );
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
              setAnnouncement((current) => current || 'Informe generado.');
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

  const courseName = jobId
    ? (navigationState?.courseName ??
      loadRememberedCourseName(jobId) ??
      `Curso ${jobId}`)
    : 'Curso';

  const downloadUrls = jobId ? getDirectReportDownloadUrls(jobId) : null;

  return (
    <LayoutSimple
      backLabel="Volver a recursos"
      backTo={jobId ? `/resources/${jobId}${getModeSearch(appMode)}` : '/'}
      description="Este informe recoge el diagnóstico completo de acceso y accesibilidad automática de los recursos analizados."
      showTokenButton={false}
      title="Informe detallado"
    >
      <p aria-live="polite" className="sr-only">
        {announcement}
      </p>

      {announcement ? (
        <div
          className="mb-6 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-success"
          role="status"
        >
          {announcement}
        </div>
      ) : null}

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
        <div className="space-y-6">
          <section className="card-panel space-y-6 p-6">
            <div className="space-y-2">
              <p className="text-sm text-subtle">{courseName}</p>
              <p className="text-sm text-subtle">
                Generado el {formatDate(report.generatedAt)}
              </p>
            </div>

            <div className="grid gap-4 sm:grid-cols-3">
              <article className="rounded-2xl border border-line bg-[var(--color-surface-soft)] p-4">
                <p className="text-sm text-subtle">Score global</p>
                <p
                  className={classNames(
                    'mt-2 text-3xl font-semibold tracking-[-0.04em]',
                    getScoreClass(getReportScore(report)),
                  )}
                >
                  {getReportScore(report)}/100
                </p>
              </article>

              <article className="rounded-2xl border border-line bg-[var(--color-surface-soft)] p-4">
                <p className="text-sm text-subtle">Recursos analizados</p>
                <p className="mt-2 text-3xl font-semibold text-ink">
                  {report.resourceCount}
                </p>
              </article>

              <article className="rounded-2xl border border-rose-200 bg-rose-50 p-4">
                <p className="text-sm text-subtle">Incidencias principales</p>
                <p className="mt-2 text-3xl font-semibold text-ink">
                  {report.failedItemCount}
                </p>
              </article>
            </div>

            <p className="text-sm leading-6 text-subtle">
              Las descargas contienen el detalle técnico completo por recurso,
              con evidencias y recomendaciones.
            </p>

            <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
              <a className="button-primary" href={downloadUrls.pdf}>
                Descargar PDF
              </a>
              <a className="button-secondary" href={downloadUrls.docx}>
                Descargar Word
              </a>
              <a className="button-secondary" href={downloadUrls.json}>
                Descargar JSON
              </a>
            </div>
          </section>
        </div>
      ) : null}
    </LayoutSimple>
  );
}
