import { FormEvent, useEffect, useRef, useState } from 'react';
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
  const initialModeParam = searchParams.get('mode');
  const [selectedMode, setSelectedMode] = useState<AppMode>(() =>
    resolveInitialMode(initialModeParam),
  );
  const lastSyncedModeRef = useRef<AppMode | null>(
    isAppMode(initialModeParam) ? initialModeParam : null,
  );
  const modeParam = searchParams.get('mode');

  useEffect(() => {
    const nextMode = isAppMode(modeParam) ? modeParam : null;

    if (!nextMode) {
      lastSyncedModeRef.current = selectedMode;
      setSearchParams({ mode: selectedMode }, { replace: true });
      rememberAppMode(selectedMode);
      return;
    }

    if (nextMode !== lastSyncedModeRef.current) {
      lastSyncedModeRef.current = nextMode;
      setSelectedMode(nextMode);
      rememberAppMode(nextMode);
    }
  }, [modeParam, selectedMode, setSearchParams]);

  const handleModeChange = (mode: AppMode) => {
    lastSyncedModeRef.current = mode;
    setSelectedMode(mode);
    rememberAppMode(mode);
    setSearchParams({ mode }, { replace: true });
  };

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
              const inputId = `analysis-mode-${option.mode}`;
              const descriptionId = `mode-${option.mode}-description`;
              const isSelected = selectedMode === option.mode;

              return (
                <div
                  key={option.mode}
                  className={classNames(
                    'rounded-2xl border p-4 transition sm:p-5',
                    isSelected
                      ? 'border-ink bg-[#f7faf7]'
                      : 'border-line bg-white hover:border-[#9cb3a2]',
                  )}
                >
                  <div className="grid grid-cols-[auto_1fr] items-start gap-4">
                    <input
                      aria-describedby={descriptionId}
                      checked={isSelected}
                      className="mt-1 h-5 w-5 accent-[#205e3c]"
                      id={inputId}
                      name="analysis-mode"
                      onChange={() => handleModeChange(option.mode)}
                      type="radio"
                      value={option.mode}
                    />

                    <div className="space-y-2">
                      <label
                        className="block cursor-pointer text-lg font-semibold text-ink"
                        htmlFor={inputId}
                      >
                        {option.label}
                      </label>
                      <p className="text-sm leading-6 text-subtle" id={descriptionId}>
                        {option.description}
                      </p>
                    </div>
                  </div>
                </div>
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
