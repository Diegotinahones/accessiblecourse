import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';
import { ProgressBar } from '../components/ProgressBar';
import { api } from '../lib/api';
import type { JobStatus } from '../lib/types';

export function AnalyzingPage() {
  const navigate = useNavigate();
  const { jobId } = useParams<{ jobId: string }>();
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const hasNavigatedRef = useRef(false);

  useEffect(() => {
    if (!jobId) {
      setError('Falta el identificador del análisis.');
      return;
    }

    let active = true;
    let intervalId = 0;

    const loadStatus = async () => {
      try {
        const nextStatus = await api.getJobStatus(jobId);
        if (!active) {
          return;
        }

        setJobStatus(nextStatus);
        setError(nextStatus.status === 'error' ? nextStatus.message : null);

        if (
          !hasNavigatedRef.current &&
          (nextStatus.status === 'done' || nextStatus.progress >= 100)
        ) {
          hasNavigatedRef.current = true;
          window.clearInterval(intervalId);
          navigate(`/resources/${jobId}`, { replace: true });
          return;
        }

        if (nextStatus.status !== 'processing') {
          window.clearInterval(intervalId);
        }
      } catch (caughtError) {
        if (!active) {
          return;
        }

        setError(
          caughtError instanceof Error
            ? caughtError.message
            : 'Ha ocurrido un error inesperado.',
        );
        window.clearInterval(intervalId);
      }
    };

    void loadStatus();
    intervalId = window.setInterval(() => {
      void loadStatus();
    }, 1200);

    return () => {
      active = false;
      window.clearInterval(intervalId);
    };
  }, [jobId, navigate]);

  const progress = jobStatus?.progress ?? 0;
  const statusMessage = jobStatus?.message ?? 'Preparando análisis…';
  const liveMessage = `Analizando… ${progress}%`;

  return (
    <LayoutSimple
      backLabel="Volver a subir"
      backTo="/"
      description="Analizando el curso y preparando el inventario real."
      title="Analizando curso"
    >
      <section className="card-panel mx-auto max-w-2xl space-y-6 p-6 sm:p-8">
        {error ? (
          <div
            aria-live="assertive"
            className="rounded-2xl border border-rose-200 bg-rose-50 p-5 text-danger"
            role="alert"
          >
            <p className="text-base font-semibold">No hemos podido completar el análisis.</p>
            <p className="mt-2 text-sm">{error}</p>
          </div>
        ) : (
          <>
            <ProgressBar label="Progreso del análisis" value={progress} />
            <p aria-live="polite" className="text-base font-medium text-ink">
              {liveMessage}
            </p>
            <p className="text-sm text-subtle">{statusMessage}</p>
          </>
        )}
      </section>
    </LayoutSimple>
  );
}
