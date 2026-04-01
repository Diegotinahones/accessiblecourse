import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { LayoutSimple } from '../components/LayoutSimple';
import { ApiError, fetchReport, generateReport, getReportDownloadUrl } from '../lib/api';
import type { ReportIssue, ReportResponse } from '../lib/types';
import {
  formatDate,
  getReportIssueStatusLabel,
  getReportSeverityLabel,
} from '../lib/types';

const DEFAULT_JOB_ID = 'demo-accessible-course';

function issueAccent(issue: ReportIssue): string {
  if (issue.status === 'FAIL' && issue.severity === 'HIGH') {
    return 'border-rose-300 bg-rose-50';
  }
  if (issue.status === 'FAIL') {
    return 'border-amber-300 bg-amber-50';
  }
  return 'border-slate-200 bg-slate-50';
}

function issueBadge(issue: ReportIssue): string {
  if (issue.status === 'FAIL' && issue.severity === 'HIGH') {
    return 'border-rose-200 bg-rose-100 text-danger';
  }
  if (issue.status === 'FAIL') {
    return 'border-amber-200 bg-amber-100 text-warning';
  }
  return 'border-slate-200 bg-white text-slate-600';
}

export function ReportPage() {
  const params = useParams<{ jobId: string }>();
  const jobId = params.jobId ?? DEFAULT_JOB_ID;
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchReport(jobId)
      .then((payload) => {
        if (!cancelled) {
          setReport(payload);
        }
      })
      .catch((loadError) => {
        if (cancelled) {
          return;
        }

        if (loadError instanceof ApiError && loadError.status === 404) {
          setReport(null);
          return;
        }

        setError(loadError instanceof Error ? loadError.message : 'No se pudo cargar el informe.');
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [jobId]);

  async function handleGenerateReport() {
    setGenerating(true);
    setError(null);

    try {
      const payload = await generateReport(jobId, { includePending: true, onlyFails: false });
      setReport(payload);
    } catch (generationError) {
      setError(generationError instanceof Error ? generationError.message : 'No se pudo generar el informe.');
    } finally {
      setGenerating(false);
    }
  }

  return (
    <LayoutSimple
      title="Informe generado"
      description="Genera un informe accionable a partir de la checklist persistida y descárgalo en PDF o Word."
      backTo={`/jobs/${jobId}/review`}
      backLabel="Volver a revisión"
    >
      {error ? (
        <div
          aria-live="assertive"
          className="mb-6 rounded-2xl border border-rose-200 bg-rose-50 p-5 text-danger"
          role="alert"
        >
          {error}
        </div>
      ) : null}

      {loading ? (
        <div aria-live="polite" className="card-panel p-8 text-subtle">
          Cargando último informe generado...
        </div>
      ) : null}

      {!loading && !report ? (
        <section className="card-panel space-y-5 p-6">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.16em] text-subtle">Pantalla 4</p>
            <h2 className="mt-2 text-2xl font-semibold text-ink">Todavía no hay informe</h2>
            <p className="mt-3 max-w-3xl text-sm leading-7 text-subtle">
              Cuando pulses generar, el backend leerá la checklist guardada en base de datos, construirá el informe
              agrupado por ruta y dejará lista la descarga en PDF, Word y JSON.
            </p>
          </div>

          <button
            type="button"
            className="button-primary"
            onClick={handleGenerateReport}
            disabled={generating}
          >
            {generating ? 'Generando informe...' : 'Generar informe'}
          </button>
        </section>
      ) : null}

      {report ? (
        <div className="space-y-6">
          <section className="card-panel grid gap-5 p-6 lg:grid-cols-[minmax(0,1fr),auto] lg:items-start">
            <div>
              <p className="text-sm font-semibold uppercase tracking-[0.16em] text-subtle">Pantalla 4</p>
              <h2 className="mt-2 text-2xl font-semibold text-ink">AccessibleCourse - Informe de accesibilidad</h2>
              <p className="mt-3 max-w-3xl text-sm leading-7 text-subtle">
                {report.meta.courseTitle ? `Curso: ${report.meta.courseTitle}. ` : ''}
                Generado el {formatDate(report.createdAt)} para el job <span className="font-semibold">{report.meta.jobId}</span>.
              </p>
              <p className="mt-2 text-sm text-subtle">Versión del sistema: {report.meta.systemVersion}</p>
            </div>

            <div className="flex flex-col gap-3 sm:flex-row lg:flex-col">
              <button
                type="button"
                className="button-primary"
                onClick={handleGenerateReport}
                disabled={generating}
              >
                {generating ? 'Regenerando...' : 'Generar informe'}
              </button>
              <a className="button-secondary" href={getReportDownloadUrl(report.files.pdfUrl)}>
                Descargar PDF
              </a>
              <a className="button-secondary" href={getReportDownloadUrl(report.files.docxUrl)}>
                Descargar Word
              </a>
            </div>
          </section>

          <section aria-live="polite" className="grid gap-4 md:grid-cols-3">
            <article className="card-panel p-6">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-subtle">Recursos analizados</p>
              <p className="mt-3 text-4xl font-semibold text-ink">{report.stats.resources}</p>
            </article>
            <article className="card-panel border-rose-200 bg-rose-50 p-6">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-subtle">Ítems FAIL</p>
              <p className="mt-3 text-4xl font-semibold text-ink">{report.stats.fails}</p>
            </article>
            <article className="card-panel border-amber-200 bg-amber-50 p-6">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-subtle">Ítems PENDING</p>
              <p className="mt-3 text-4xl font-semibold text-ink">{report.stats.pending}</p>
            </article>
          </section>

          <section className="grid gap-6 lg:grid-cols-[minmax(0,1fr),minmax(280px,340px)]">
            <article className="card-panel p-6">
              <p className="text-sm font-semibold uppercase tracking-[0.16em] text-subtle">Resumen ejecutivo</p>
              <h3 className="mt-2 text-xl font-semibold text-ink">Top recursos con más FAIL</h3>

              {report.summary.topResources.length === 0 ? (
                <p className="mt-4 text-sm text-subtle">No hay recursos con FAIL registrados.</p>
              ) : (
                <ol className="mt-4 space-y-3">
                  {report.summary.topResources.map((resource, index) => (
                    <li key={resource.resourceId} className="rounded-2xl border border-line bg-white p-4">
                      <p className="text-sm font-semibold text-ink">
                        {index + 1}. {resource.title}
                      </p>
                      <p className="mt-2 text-sm text-subtle">{resource.coursePath}</p>
                      <p className="mt-2 text-sm font-semibold text-danger">{resource.failCount} FAIL</p>
                    </li>
                  ))}
                </ol>
              )}
            </article>

            <article className="card-panel p-6">
              <p className="text-sm font-semibold uppercase tracking-[0.16em] text-subtle">Recomendaciones</p>
              <h3 className="mt-2 text-xl font-semibold text-ink">Acciones generales</h3>
              <ul className="mt-4 space-y-3">
                {report.summary.recommendations.map((recommendation) => (
                  <li key={recommendation} className="rounded-2xl border border-line bg-panel p-4 text-sm leading-7 text-slate-700">
                    {recommendation}
                  </li>
                ))}
              </ul>
            </article>
          </section>

          <section className="card-panel p-6">
            <div className="flex flex-col gap-3 border-b border-line pb-5 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-sm font-semibold uppercase tracking-[0.16em] text-subtle">Detalle principal</p>
                <h3 className="mt-2 text-xl font-semibold text-ink">Hallazgos agrupados por ruta y recurso</h3>
              </div>
              <a className="button-secondary" href={getReportDownloadUrl(report.files.jsonUrl)}>
                Descargar JSON
              </a>
            </div>

            {report.routes.length === 0 ? (
              <div className="mt-6 rounded-2xl border border-emerald-200 bg-emerald-50 p-5 text-success">
                No hay ítems FAIL o PENDING en la checklist actual.
              </div>
            ) : (
              <div className="mt-6 space-y-6">
                {report.routes.map((route) => (
                  <article key={route.coursePath} className="rounded-3xl border border-line bg-white p-5">
                    <div className="flex flex-col gap-3 border-b border-line pb-4 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <p className="text-sm font-semibold uppercase tracking-[0.16em] text-subtle">Ruta</p>
                        <h4 className="mt-2 text-xl font-semibold text-ink">{route.coursePath}</h4>
                      </div>
                      <div className="grid gap-2 text-sm text-subtle sm:text-right">
                        <span>{route.stats.resources} recurso(s)</span>
                        <span>{route.stats.fails} FAIL</span>
                        <span>{route.stats.pending} PENDING</span>
                      </div>
                    </div>

                    <div className="mt-5 space-y-5">
                      {route.resources.map((resource) => (
                        <section key={resource.resourceId} className="rounded-2xl border border-line bg-panel p-5">
                          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                            <div>
                              <p className="text-sm font-semibold uppercase tracking-[0.16em] text-subtle">
                                {resource.type} · {resource.origin}
                              </p>
                              <h5 className="mt-2 text-lg font-semibold text-ink">{resource.title}</h5>
                              <p className="mt-2 text-sm text-subtle">
                                {resource.coursePath}
                                {resource.source ? ` · ${resource.source}` : ''}
                              </p>
                            </div>
                            <div className="grid gap-2 text-sm text-subtle lg:text-right">
                              <span>{resource.stats.fails} FAIL</span>
                              <span>{resource.stats.pending} PENDING</span>
                            </div>
                          </div>

                          <ul className="mt-4 space-y-3">
                            {[...resource.fails, ...resource.pending].map((issue) => (
                              <li key={`${resource.resourceId}-${issue.itemKey}-${issue.status}`} className={`rounded-2xl border p-4 ${issueAccent(issue)}`}>
                                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                                  <div>
                                    <p className="font-semibold text-ink">{issue.label}</p>
                                    <p className="mt-2 text-sm leading-7 text-slate-700">{issue.description}</p>
                                  </div>
                                  <span className={`inline-flex rounded-full border px-3 py-1 text-sm font-semibold ${issueBadge(issue)}`}>
                                    {getReportIssueStatusLabel(issue.status)} · {getReportSeverityLabel(issue.severity)}
                                  </span>
                                </div>

                                <div className="mt-4 rounded-2xl border border-slate-200 bg-white p-4">
                                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-subtle">Cómo arreglarlo</p>
                                  <p className="mt-2 text-sm leading-7 text-slate-700">
                                    {issue.recommendation ?? 'Sin recomendación registrada para este criterio.'}
                                  </p>
                                </div>

                                {issue.comment ? (
                                  <div className="mt-4 rounded-2xl border border-slate-200 bg-white p-4">
                                    <p className="text-xs font-semibold uppercase tracking-[0.16em] text-subtle">Notas del revisor</p>
                                    <p className="mt-2 text-sm leading-7 text-slate-700">{issue.comment}</p>
                                  </div>
                                ) : null}
                              </li>
                            ))}
                          </ul>
                        </section>
                      ))}
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>

          <section className="card-panel p-6">
            <p className="text-sm font-semibold uppercase tracking-[0.16em] text-subtle">Apéndice</p>
            <h3 className="mt-2 text-xl font-semibold text-ink">Definición de estados</h3>
            <div className="mt-4 grid gap-3 md:grid-cols-3">
              {Object.entries(report.appendix.statusDefinitions).map(([status, description]) => (
                <article key={status} className="rounded-2xl border border-line bg-panel p-4">
                  <p className="text-sm font-semibold text-ink">{status}</p>
                  <p className="mt-2 text-sm leading-7 text-subtle">{description}</p>
                </article>
              ))}
            </div>
          </section>

          <div className="flex flex-col gap-3 sm:flex-row">
            <Link className="button-secondary" to={`/jobs/${jobId}/review`}>
              Volver a recursos
            </Link>
          </div>
        </div>
      ) : null}
    </LayoutSimple>
  );
}
