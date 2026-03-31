import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { LayoutSimple } from '../components/LayoutSimple';
import { ReviewStateBadge, SessionStatusBadge } from '../components/StatusBadge';
import { exportReport, fetchSummary } from '../lib/api';
import type { ReportResponse, ReviewSummary } from '../lib/types';
import { formatDate, getResourceTypeLabel } from '../lib/types';

const DEFAULT_JOB_ID = 'demo-accessible-course';

export function ReportPage() {
  const params = useParams<{ jobId: string }>();
  const jobId = params.jobId ?? DEFAULT_JOB_ID;
  const [summary, setSummary] = useState<ReviewSummary | null>(null);
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchSummary(jobId)
      .then((payload) => {
        if (!cancelled) {
          setSummary(payload);
        }
      })
      .catch((loadError: Error) => {
        if (!cancelled) {
          setError(loadError.message);
        }
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

  async function handleExport() {
    setExporting(true);
    try {
      const payload = await exportReport(jobId);
      setReport(payload);
      setError(null);
    } catch (exportError) {
      setError(exportError instanceof Error ? exportError.message : 'No se pudo generar el JSON del informe.');
    } finally {
      setExporting(false);
    }
  }

  return (
    <LayoutSimple
      title="Informe generado"
      description="Resumen persistido de los incumplimientos agrupados por recurso y listo para exportar como JSON."
      backTo={`/jobs/${jobId}/review`}
      backLabel="Volver a revisión"
    >
      {error ? <p className="error-banner">{error}</p> : null}

      {loading ? (
        <div className="panel detail-panel detail-panel--empty">
          <p className="eyebrow">Pantalla 4</p>
          <h2>Cargando informe...</h2>
        </div>
      ) : null}

      {summary ? (
        <div className="summary-layout">
          <section className="panel panel--hero">
            <div>
              <p className="eyebrow">Pantalla 4</p>
              <h2>Informe de accesibilidad</h2>
              <p>El resumen lee directamente la base de datos y agrupa los FAIL por recurso con su recomendación asociada.</p>
            </div>
            <div className="hero__meta">
              <div>
                <span className="detail-meta__label">Sesión</span>
                <SessionStatusBadge status={summary.reviewSession.status} />
              </div>
              <div>
                <span className="detail-meta__label">Última actualización</span>
                <strong>{formatDate(summary.lastUpdated)}</strong>
              </div>
            </div>
          </section>

          <section className="summary-stats">
            <article className="summary-stat">
              <span>Recursos</span>
              <strong>{summary.totalResources}</strong>
            </article>
            <article className="summary-stat summary-stat--danger">
              <span>Ítems FAIL</span>
              <strong>{summary.totalFailItems}</strong>
            </article>
          </section>

          <section className="panel summary-board">
            <div className="summary-board__header">
              <div>
                <p className="eyebrow">Hallazgos</p>
                <h2>Incumplimientos agrupados por recurso</h2>
              </div>
              <button type="button" className="primary-button" onClick={handleExport} disabled={exporting}>
                {exporting ? 'Generando JSON...' : 'Exportar JSON'}
              </button>
            </div>

            {summary.resources.length === 0 ? (
              <div className="empty-summary">
                <h3>No hay incumplimientos registrados.</h3>
                <p>Cuando un criterio se marque como “No cumple”, aparecerá aquí con su recomendación.</p>
              </div>
            ) : (
              <div className="summary-groups">
                {summary.resources.map((resource) => (
                  <article key={resource.resourceId} className="summary-group">
                    <div className="summary-group__header">
                      <div>
                        <p className="eyebrow">{getResourceTypeLabel(resource.resourceType)}</p>
                        <h3>{resource.title}</h3>
                      </div>
                      <ReviewStateBadge state={resource.reviewState} />
                    </div>

                    <ul className="recommendation-list">
                      {resource.recommendations.map((recommendation) => (
                        <li key={`${resource.resourceId}-${recommendation.itemKey}`}>
                          <strong>{recommendation.label}</strong>
                          <p>{recommendation.recommendation ?? 'Sin recomendación disponible.'}</p>
                          {recommendation.comment ? <span>Observación docente: {recommendation.comment}</span> : null}
                        </li>
                      ))}
                    </ul>
                  </article>
                ))}
              </div>
            )}

            {report ? (
              <div className="report-preview">
                <div className="report-preview__header">
                  <h3>Export placeholder</h3>
                  <span>{formatDate(report.generatedAt)}</span>
                </div>
                <pre>{JSON.stringify(report, null, 2)}</pre>
              </div>
            ) : null}
          </section>

          <div className="summary-footer">
            <Link className="secondary-button" to={`/jobs/${jobId}/review`}>
              Volver a recursos
            </Link>
          </div>
        </div>
      ) : null}
    </LayoutSimple>
  );
}
