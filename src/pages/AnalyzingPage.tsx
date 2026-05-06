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

  if (status?.phase === 'HTML_ACCESSIBILITY_SCAN') {
    return {
      context: 'Analizando la accesibilidad de las páginas HTML.',
      title: 'Procesando accesibilidad de los recursos HTML',
    };
  }

  if (status?.phase === 'PDF_ACCESSIBILITY_SCAN') {
    return {
      context:
        'Analizando la accesibilidad de los documentos PDF. La fase HTML ya se ha completado.',
      title: 'Procesando accesibilidad de los recursos PDF',
    };
  }

  if (status?.phase === 'DOCX_ACCESSIBILITY_SCAN') {
    return {
      context:
        'Analizando la accesibilidad de los documentos Word. Las fases HTML y PDF ya se han completado.',
      title: 'Procesando accesibilidad de los documentos Word',
    };
  }

  if (status?.phase === 'VIDEO_ACCESSIBILITY_SCAN') {
    return {
      context:
        'Verificando subtítulos, transcripción, proveedor y accesibilidad básica de los vídeos.',
      title: 'Procesando accesibilidad de los recursos de vídeo',
    };
  }

  if (status?.phase === 'DONE') {
    return {
      context: null,
      title: 'Análisis completado',
    };
  }

  if (progress >= 99) {
    return {
      context: null,
      title: 'Análisis completado',
    };
  }

  if (progress >= 97) {
    return {
      context:
        'Verificando subtítulos, transcripción, proveedor y accesibilidad básica de los vídeos.',
      title: 'Procesando accesibilidad de los recursos de vídeo',
    };
  }

  if (progress >= 95) {
    return {
      context:
        'Analizando la accesibilidad de los documentos Word. Las fases HTML y PDF ya se han completado.',
      title: 'Procesando accesibilidad de los documentos Word',
    };
  }

  if (progress >= 90) {
    return {
      context:
        'Analizando la accesibilidad de los documentos PDF. La fase HTML ya se ha completado.',
      title: 'Procesando accesibilidad de los recursos PDF',
    };
  }

  if (progress >= 85) {
    return {
      context: 'Analizando la accesibilidad de las páginas HTML.',
      title: 'Procesando accesibilidad de los recursos HTML',
    };
  }

  if (progress >= 75) {
    return { context: null, title: 'Buscando descargables' };
  }

  if (progress >= 50) {
    return { context: null, title: 'Comprobando acceso' };
  }

  if (progress >= 25) {
    return { context: null, title: 'Detectando recursos' };
  }

  return { context: null, title: 'Leyendo estructura del curso' };
}

function isAccessibilityScanPhase(status: JobStatus | null) {
  return (
    status?.phase === 'HTML_ACCESSIBILITY_SCAN' ||
    status?.phase === 'PDF_ACCESSIBILITY_SCAN' ||
    status?.phase === 'DOCX_ACCESSIBILITY_SCAN' ||
    status?.phase === 'VIDEO_ACCESSIBILITY_SCAN'
  );
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
  const statusCopy = getAnalysisCopy(jobStatus);
  const currentStep = jobStatus?.currentStep ?? 1;
  const totalSteps = jobStatus?.totalSteps ?? 1;
  const liveMessage = `${statusCopy.title}. ${progress}% completado.`;
  const backendMessage = isAccessibilityScanPhase(jobStatus)
    ? null
    : jobStatus?.message;

  return (
    <LayoutSimple
      backLabel="Volver"
      backTo={`/${appMode}${getModeSearch(appMode)}`}
      description="Estamos preparando el diagnóstico de acceso a recursos."
      title="Analizando recursos"
    >
      <section className="mx-auto max-w-2xl space-y-6 rounded-3xl border border-line bg-white p-6 shadow-card sm:p-8">
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
            <p aria-live="polite" className="text-base font-medium text-ink">
              {liveMessage}
            </p>
            {statusCopy.context ? (
              <p className="text-sm leading-6 text-subtle">
                {statusCopy.context}
              </p>
            ) : null}
            <p className="text-sm font-semibold uppercase tracking-[0.16em] text-subtle">
              Paso {currentStep} de {totalSteps}
            </p>
            {backendMessage ? (
              <p className="text-sm leading-6 text-subtle">{backendMessage}</p>
            ) : null}
          </>
        )}
      </section>
    </LayoutSimple>
  );
}
