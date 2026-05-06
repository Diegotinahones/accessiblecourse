import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';
import { ProgressBar } from '../components/ProgressBar';
import { api } from '../lib/api';
import type { AppMode, JobStatus } from '../lib/types';
import {
  getModeSearch,
  isAppMode,
  loadRememberedAppMode,
  rememberAppMode,
} from '../lib/utils';

function getAnalysisCopy(status: JobStatus | null) {
  const progress = status?.progress ?? 0;

  if (status?.phase === 'UPLOAD') {
    return 'Accediendo al curso';
  }

  if (status?.phase === 'INVENTORY') {
    return 'Detectando recursos';
  }

  if (status?.phase === 'ACCESS_SCAN') {
    return progress >= 75 ? 'Buscando descargables' : 'Accediendo al curso';
  }

  if (status?.phase === 'HTML_ACCESSIBILITY_SCAN') {
    return 'Analizando HTML';
  }

  if (status?.phase === 'PDF_ACCESSIBILITY_SCAN') {
    return 'Analizando PDF';
  }

  if (status?.phase === 'DOCX_ACCESSIBILITY_SCAN') {
    return 'Analizando Word';
  }

  if (status?.phase === 'VIDEO_ACCESSIBILITY_SCAN') {
    return 'Analizando vídeo';
  }

  if (status?.phase === 'DONE') {
    return 'Análisis completado';
  }

  if (progress >= 99) {
    return 'Análisis completado';
  }

  if (progress >= 97) {
    return 'Analizando vídeo';
  }

  if (progress >= 95) {
    return 'Analizando Word';
  }

  if (progress >= 90) {
    return 'Analizando PDF';
  }

  if (progress >= 85) {
    return 'Analizando HTML';
  }

  if (progress >= 75) {
    return 'Buscando descargables';
  }

  if (progress >= 50) {
    return 'Accediendo al curso';
  }

  if (progress >= 25) {
    return 'Detectando recursos';
  }

  return 'Accediendo al curso';
}

export function AnalyzingPage() {
  const navigate = useNavigate();
  const { jobId } = useParams<{ jobId: string }>();
  const [searchParams] = useSearchParams();
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const hasNavigatedRef = useRef(false);
  const modeParam = searchParams.get('mode');
  const appMode: AppMode = isAppMode(modeParam)
    ? modeParam
    : (loadRememberedAppMode() ?? 'offline');

  useEffect(() => {
    rememberAppMode(appMode);
  }, [appMode]);

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
          navigate(`/resources/${jobId}${getModeSearch(appMode)}`, {
            replace: true,
          });
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
  }, [appMode, jobId, navigate]);

  const progress = jobStatus?.progress ?? 0;
  const statusMessage = getAnalysisCopy(jobStatus);
  const liveMessage = `${statusMessage}. ${progress}% completado.`;

  return (
    <LayoutSimple
      backLabel="Volver"
      backTo={`/${appMode}${getModeSearch(appMode)}`}
      description="Esto puede tardar unos minutos."
      showTokenButton={false}
      title="Estamos analizando los recursos"
    >
      <section className="mx-auto max-w-2xl space-y-6 rounded-3xl border border-line bg-white p-6 text-center shadow-card sm:p-8">
        {error ? (
          <div
            aria-live="assertive"
            className="rounded-2xl border border-rose-200 bg-rose-50 p-5 text-danger"
            role="alert"
          >
            <p className="text-base font-semibold">
              No hemos podido completar el análisis.
            </p>
            <p className="mt-2 text-sm">{error}</p>
          </div>
        ) : (
          <>
            <ProgressBar label="Progreso del análisis" value={progress} />
            <p aria-live="polite" className="text-lg font-semibold text-ink">
              {liveMessage}
            </p>
          </>
        )}
      </section>
    </LayoutSimple>
  );
}
