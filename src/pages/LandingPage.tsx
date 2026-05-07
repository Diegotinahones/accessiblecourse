import { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';
import { getModeRoute, rememberAppMode } from '../lib/utils';

interface LandingPageProps {
  tokenActive: boolean;
  tokenConfigured: boolean;
  tokenStatusError: string | null;
}

export function LandingPage({
  tokenActive,
  tokenConfigured,
  tokenStatusError,
}: LandingPageProps) {
  const navigate = useNavigate();
  const [, setSearchParams] = useSearchParams();

  useEffect(() => {
    setSearchParams({}, { replace: true });
  }, [setSearchParams]);

  const chooseMode = (mode: 'online' | 'offline') => {
    rememberAppMode(mode);
    navigate(getModeRoute(mode));
  };

  return (
    <LayoutSimple
      align="center"
      description="Elige cómo quieres empezar."
      showTokenButton={tokenConfigured}
      title="Haz tu curso accesible"
      useMainLandmark={false}
    >
      <div className="mx-auto max-w-4xl space-y-6">
        {tokenStatusError ? (
          <p
            aria-live="polite"
            className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-[#8a5a00]"
            role="status"
          >
            {tokenStatusError} Puedes continuar con el modo offline.
          </p>
        ) : null}

        <div className="grid gap-4 sm:grid-cols-2">
          <button
            className="choice-panel min-h-48 text-left focus-visible:outline focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-[var(--uoc-cyan)]"
            onClick={() => chooseMode('online')}
            type="button"
          >
            <span className="block text-2xl font-semibold tracking-[-0.03em] text-ink">
              Online
            </span>
            <span className="mt-4 block text-base leading-7 text-subtle">
              Usaremos tu token para acceder a los cursos de Canvas/UOC a los
              que tienes acceso.
            </span>
            {!tokenActive ? (
              <span className="mt-4 block text-sm font-semibold leading-6 text-[#8a5a00]">
                Requiere configurar un token de acceso antes de cargar cursos.
              </span>
            ) : null}
          </button>

          <button
            className="choice-panel min-h-48 text-left focus-visible:outline focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-[var(--uoc-cyan)]"
            onClick={() => chooseMode('offline')}
            type="button"
          >
            <span className="block text-2xl font-semibold tracking-[-0.03em] text-ink">
              Offline
            </span>
            <span className="mt-4 block text-base leading-7 text-subtle">
              Sube un archivo IMSCC o ZIP exportado del curso.
            </span>
          </button>
        </div>
      </div>
    </LayoutSimple>
  );
}
