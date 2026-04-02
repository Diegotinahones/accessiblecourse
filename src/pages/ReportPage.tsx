import { useEffect, useMemo, useState } from 'react';
import { useLocation, useParams } from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';
import {
  ApiError,
  fetchReport,
  generateReport,
  getDirectReportDownloadUrls,
} from '../lib/api';
import type { GeneratedReport } from '../lib/types';
import { formatDate } from '../lib/types';
import { loadRememberedCourseName } from '../lib/utils';

interface ReportLocationState {
  announcement?: string;
  courseName?: string | null;
}

function getLoadMessage(isGenerating: boolean) {
  return isGenerating ? 'Generando informe…' : 'Cargando informe…';
}

export function ReportPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const location = useLocation();
  const navigationState = (location.state as ReportLocationState | null) ?? null;
  const [report, setReport] = useState<GeneratedReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [announcement, setAnnouncement] = useState(navigationState?.announcement ?? '');

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
          loadError instanceof Error ? loadError.message : 'No se pudo cargar el informe.',
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
    ? navigationState?.courseName ?? loadRememberedCourseName(jobId) ?? `Curso ${jobId}`
    : 'Curso';

  const downloadUrls = jobId ? getDirectReportDownloadUrls(jobId) : null;

  const sortedGroups = useMemo(() => {
    if (!report) {
      return [];
    }

    return [...report.groups].sort((left, right) => {
      const failureDifference = right.failures.length - left.failures.length;
      if (failureDifference !== 0) {
        return failureDifference;
      }

      return left.resource.title.localeCompare(right.resource.title, 'es');
    });
  }, [report]);

  return (
    <LayoutSimple
      backLabel="Volver a recursos"
      backTo={jobId ? `/resources/${jobId}` : '/'}
      description="Este informe se ha generado a partir de una checklist revisada manualmente."
      title="Informe"
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
          <section className="card-panel space-y-5 p-6">
            <div className="space-y-2">
              <p className="text-sm text-subtle">{courseName}</p>
              <p className="text-sm text-subtle">
                Generado el {formatDate(report.generatedAt)}
              </p>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <article className="rounded-2xl border border-line bg-[#f9faf7] p-4">
                <p className="text-sm text-subtle">Recursos analizados</p>
                <p className="mt-2 text-3xl font-semibold text-ink">
                  {report.resourceCount}
                </p>
              </article>

              <article className="rounded-2xl border border-rose-200 bg-rose-50 p-4">
                <p className="text-sm text-subtle">Ítems FAIL</p>
                <p className="mt-2 text-3xl font-semibold text-ink">
                  {report.failedItemCount}
                </p>
              </article>
            </div>

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

          <section className="card-panel overflow-hidden">
            <h2>
              <button
                aria-controls="report-detail-panel"
                aria-expanded={detailsOpen}
                className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left text-base font-semibold text-ink sm:px-6"
                id="report-detail-button"
                onClick={() => setDetailsOpen((current) => !current)}
                type="button"
              >
                <span>{detailsOpen ? 'Ocultar detalle' : 'Ver detalle'}</span>
                <span className="text-sm font-medium text-subtle">
                  {sortedGroups.length}
                </span>
              </button>
            </h2>

            <div
              aria-labelledby="report-detail-button"
              className="border-t border-line"
              hidden={!detailsOpen}
              id="report-detail-panel"
              role="region"
            >
              {sortedGroups.length === 0 ? (
                <div className="p-6 text-sm text-subtle">
                  No hay incidencias FAIL registradas en este informe.
                </div>
              ) : (
                <div className="space-y-4 p-4 sm:p-6">
                  {sortedGroups.map((group) => (
                    <article
                      className="rounded-2xl border border-line p-4"
                      key={group.resource.id}
                    >
                      <div className="space-y-1">
                        <h3 className="text-base font-semibold text-ink">
                          {group.resource.title}
                        </h3>
                      </div>

                      <ul className="mt-4 space-y-3">
                        {group.failures.map((failure) => (
                          <li
                            className="rounded-2xl border border-rose-200 bg-rose-50 p-4"
                            key={`${group.resource.id}-${failure.itemId}`}
                          >
                            <p className="text-sm font-semibold text-ink">
                              {failure.label}
                            </p>
                            <p className="mt-2 text-sm text-subtle">
                              {failure.recommendation}
                            </p>
                          </li>
                        ))}
                      </ul>
                    </article>
                  ))}
                </div>
              )}
            </div>
          </section>
        </div>
      ) : null}
    </LayoutSimple>
  );
}
