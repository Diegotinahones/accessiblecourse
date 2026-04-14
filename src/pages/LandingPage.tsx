import { FormEvent, useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';
import type { AppMode } from '../lib/types';
import {
  classNames,
  getModeRoute,
  isAppMode,
  loadRememberedAppMode,
  rememberAppMode,
} from '../lib/utils';

interface ModeOption {
  mode: AppMode;
  title: string;
  description: string;
  summary: string;
}

const MODE_OPTIONS: ModeOption[] = [
  {
    mode: 'online',
    title: 'ONLINE',
    description: 'Inicia sesión en la UOC (Canvas)',
    summary:
      'Accede a tu curso desde Canvas/UOC para trabajar conectando con la plataforma.',
  },
  {
    mode: 'offline',
    title: 'OFFLINE',
    description: 'Sube un archivo IMSCC',
    summary:
      'Trabaja subiendo un paquete IMSCC o ZIP exportado desde tu plataforma.',
  },
];

function resolveInitialMode(modeParam: string | null): AppMode {
  if (isAppMode(modeParam)) {
    return modeParam;
  }

  return loadRememberedAppMode() ?? 'offline';
}

export function LandingPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedMode, setSelectedMode] = useState<AppMode>(() =>
    resolveInitialMode(searchParams.get('mode')),
  );
  const currentModeParam = searchParams.get('mode');

  useEffect(() => {
    const nextMode = isAppMode(currentModeParam) ? currentModeParam : null;

    if (nextMode && nextMode !== selectedMode) {
      setSelectedMode(nextMode);
      rememberAppMode(nextMode);
      return;
    }

    rememberAppMode(selectedMode);

    if (nextMode !== selectedMode) {
      setSearchParams({ mode: selectedMode }, { replace: true });
    }
  }, [currentModeParam, selectedMode, setSearchParams]);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    rememberAppMode(selectedMode);
    navigate(getModeRoute(selectedMode));
  };

  return (
    <LayoutSimple
      align="center"
      description="Elige cómo quieres empezar: conectando con Canvas/UOC o subiendo un paquete IMSCC."
      title="Haz tu curso accesible"
    >
      <form className="card-panel mx-auto max-w-3xl space-y-6 p-6 sm:p-8" onSubmit={handleSubmit}>
        <fieldset className="space-y-4">
          <legend className="text-lg font-semibold text-ink">Selecciona un modo de uso</legend>
          <p className="text-sm leading-6 text-subtle">
            Puedes cambiar de modo más tarde. La opción seleccionada se conservará al recargar esta página.
          </p>

          <div className="space-y-4">
            {MODE_OPTIONS.map((option) => {
              const descriptionId = `mode-${option.mode}-description`;
              const summaryId = `mode-${option.mode}-summary`;
              const isSelected = selectedMode === option.mode;

              return (
                <label
                  key={option.mode}
                  className={classNames(
                    'block cursor-pointer rounded-3xl border p-5 text-left transition sm:p-6',
                    isSelected
                      ? 'border-ink bg-[#f4f7f1] shadow-sm'
                      : 'border-line bg-white hover:border-[#8da793]',
                  )}
                >
                  <div className="flex items-start gap-4">
                    <input
                      aria-describedby={`${descriptionId} ${summaryId}`}
                      checked={isSelected}
                      className="mt-1 h-5 w-5 accent-[#205e3c]"
                      name="mode"
                      onChange={() => setSelectedMode(option.mode)}
                      type="radio"
                      value={option.mode}
                    />

                    <div className="space-y-2">
                      <p className="text-sm font-semibold tracking-[0.14em] text-subtle">
                        {option.title}
                      </p>
                      <p className="text-xl font-semibold text-ink" id={descriptionId}>
                        {option.description}
                      </p>
                      <p className="text-sm leading-6 text-subtle" id={summaryId}>
                        {option.summary}
                      </p>
                    </div>
                  </div>
                </label>
              );
            })}
          </div>
        </fieldset>

        <button className="button-primary w-full sm:w-auto" type="submit">
          Continuar
        </button>
      </form>
    </LayoutSimple>
  );
}
