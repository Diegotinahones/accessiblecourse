import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';
import { ProgressBar } from '../components/ProgressBar';
import { api } from '../lib/api';
import { JobStatus } from '../lib/types';

export function AnalyzingPage() {
  const navigate = useNavigate();
  const { jobId } = useParams<{ jobId: string }>();
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) {
      setError('Falta el identificador del analisis.');
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

        if (nextStatus.status !== 'processing') {
          window.clearInterval(intervalId);
        }
      } catch (caughtError) {
        if (!active) {
          return;
        }

        setError(caughtError instanceof Error ? caughtError.message : 'Ha ocurrido un error inesperado.');
        window.clearInterval(intervalId);
      }
    };

    void loadStatus();
    intervalId = window.setInterval(() => {
      void loadStatus();
    }, 1000);

    return () => {
      active = false;
      window.clearInterval(intervalId);
    };
  }, [jobId]);

  const progress = jobStatus?.progress ?? 0;
  const isDone = jobStatus?.status === 'done';
  const isError = jobStatus?.status === 'error' || Boolean(error);

  return (
    <LayoutSimple
      backLabel="Volver a subir"
      backTo="/"
      description="Estamos recorriendo el curso y preparando un checklist inicial por recurso."
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

            <button className="button-primary" onClick={() => navigate('/')} type="button">
              Volver a subir
            </button>
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
