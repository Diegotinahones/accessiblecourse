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
import {
  getModeSearch,
  isAppMode,
  loadRememberedAppMode,
  loadRememberedCourseName,
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
