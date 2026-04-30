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
  label: string;
  description: string;
}

const MODE_OPTIONS: ModeOption[] = [
  {
    mode: 'online',
    label: 'Online (Canvas/UOC)',
    description: 'Accede a tus cursos de Canvas/UOC y elige cuál quieres analizar.',
  },
  {
    mode: 'offline',
    label: 'Offline (IMSCC/ZIP)',
    description: 'Sube un paquete IMSCC o ZIP exportado desde tu plataforma.',
  },
];

function resolveInitialMode(value: string | null): AppMode {
  if (isAppMode(value)) {
    return value;
  }

  return loadRememberedAppMode() ?? 'offline';
}

export function LandingPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedMode, setSelectedMode] = useState<AppMode>(() =>
    resolveInitialMode(searchParams.get('mode')),
  );
  const modeParam = searchParams.get('mode');

  useEffect(() => {
    const nextMode = isAppMode(modeParam) ? modeParam : null;

    if (nextMode && nextMode !== selectedMode) {
      setSelectedMode(nextMode);
      rememberAppMode(nextMode);
      return;
    }

    rememberAppMode(selectedMode);

    if (nextMode !== selectedMode) {
      setSearchParams({ mode: selectedMode }, { replace: true });
    }
  }, [modeParam, selectedMode, setSearchParams]);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    rememberAppMode(selectedMode);
    navigate(getModeRoute(selectedMode));
  };

  return (
    <LayoutSimple
      align="center"
      description="Elige cómo quieres analizarlo"
      title="Haz tu curso accesible"
    >
      <form
        className="card-panel mx-auto max-w-3xl space-y-6 p-6 sm:p-8"
        onSubmit={handleSubmit}
      >
        <fieldset className="space-y-4">
          <legend className="text-lg font-semibold text-ink">
            Selecciona el flujo de análisis
          </legend>

          <div className="space-y-4">
            {MODE_OPTIONS.map((option) => {
              const descriptionId = `mode-${option.mode}-description`;
              const isSelected = selectedMode === option.mode;

              return (
                <label
                  key={option.mode}
                  className={classNames(
                    'block cursor-pointer rounded-3xl border p-5 transition sm:p-6',
                    isSelected
                      ? 'border-ink bg-[#f7faf7]'
                      : 'border-line bg-white hover:border-[#9cb3a2]',
                  )}
                >
                  <div className="flex items-start gap-4">
                    <input
                      aria-describedby={descriptionId}
                      checked={isSelected}
                      className="mt-1 h-5 w-5 accent-[#205e3c]"
                      name="analysis-mode"
                      onChange={() => setSelectedMode(option.mode)}
                      type="radio"
                      value={option.mode}
                    />

                    <div className="space-y-2">
                      <p className="text-lg font-semibold text-ink">{option.label}</p>
                      <p className="text-sm leading-6 text-subtle" id={descriptionId}>
                        {option.description}
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
