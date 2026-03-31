import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';
import { ProgressBar } from '../components/ProgressBar';
import { api } from '../lib/api';
import { JobStatus } from '../lib/types';

export function AnalyzingPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRetrying, setIsRetrying] = useState(false);

  useEffect(() => {
    if (!jobId) {
      setError('Falta el identificador del analisis.');
      return;
    }

    let active = true;

    const loadStatus = async () => {
      try {
        const nextStatus = await api.getJobStatus(jobId);
        if (!active) {
          return;
        }

        setJobStatus(nextStatus);
        setError(nextStatus.status === 'error' ? nextStatus.message : null);
      } catch (caughtError) {
        if (!active) {
          return;
        }

        setError(caughtError instanceof Error ? caughtError.message : 'Ha ocurrido un error inesperado.');
      }
    };

    void loadStatus();
    const intervalId = window.setInterval(() => {
      void loadStatus();
    }, 1000);

    return () => {
      active = false;
      window.clearInterval(intervalId);
    };
  }, [jobId]);

  const handleRetry = async () => {
    if (!jobId) {
      return;
    }

    try {
      setIsRetrying(true);
      const nextStatus = await api.retryJob(jobId);
      setJobStatus(nextStatus);
      setError(null);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : 'No hemos podido reintentar el analisis.');
    } finally {
      setIsRetrying(false);
    }
  };

  const progress = jobStatus?.progress ?? 0;
  const isDone = jobStatus?.status === 'done';
  const isError = jobStatus?.status === 'error' || Boolean(error);

  return (
    <LayoutSimple
      backLabel="Volver a subir"
      backTo="/"
      description="Estamos recorriendo el curso, extrayendo recursos y preparando un checklist inicial por recurso."
      title="Analizando curso"
    >
      <section aria-labelledby="estado-analisis" className="card-panel p-8 sm:p-10">
        <h2 id="estado-analisis" className="text-2xl font-semibold text-ink">
          Estado del analisis
        </h2>

        {isError ? (
          <div aria-live="assertive" className="mt-6 space-y-5">
            <div className="rounded-2xl border border-rose-200 bg-rose-50 p-5 text-danger" role="alert">
              <p className="text-base font-semibold">No hemos podido completar el analisis.</p>
              <p className="mt-2 text-sm">{error}</p>
            </div>

            <div className="flex flex-col gap-3 sm:flex-row">
              <button className="button-primary" disabled={isRetrying} onClick={handleRetry} type="button">
                {isRetrying ? 'Reintentando...' : 'Reintentar'}
              </button>
              <Link className="button-secondary" to="/">
                Volver a subir
              </Link>
            </div>
          </div>
        ) : (
          <div className="mt-6 space-y-6">
            <ProgressBar label="Progreso del analisis" value={progress} />
            <div aria-live="polite" className="space-y-2">
              <p className="text-base font-semibold text-ink">
                Paso {jobStatus?.currentStep ?? 1} de {jobStatus?.totalSteps ?? 4}
              </p>
              <p className="text-sm text-subtle">{jobStatus?.message ?? 'Preparando analisis...'}</p>
            </div>

            {isDone ? (
              <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5">
                <p className="text-base font-semibold text-success">El curso ya esta listo para revisar.</p>
                <Link className="button-primary mt-5" to={`/resources/${jobId}`}>
                  Ver recursos
                </Link>
              </div>
            ) : null}
          </div>
        )}
      </section>
    </LayoutSimple>
  );
}
