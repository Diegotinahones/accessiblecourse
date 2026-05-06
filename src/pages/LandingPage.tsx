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
    description: 'Analiza recursos directamente desde un aula online.',
  },
  {
    mode: 'offline',
    label: 'Offline (IMSCC/ZIP)',
    description:
      'Sube un paquete exportado para analizarlo sin conexión a Canvas.',
  },
];

function resolveInitialMode(value: string | null): AppMode {
  if (isAppMode(value)) {
    return value;
  }

  return loadRememberedAppMode() ?? 'offline';
}

interface LandingPageProps {
  tokenActive: boolean;
  tokenStatusError: string | null;
}

export function LandingPage({
  tokenActive,
  tokenStatusError,
}: LandingPageProps) {
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
      description="Haz tu curso accesible"
      title="AccessibleCourse"
    >
      <form
        className="mx-auto max-w-3xl space-y-7 rounded-3xl border border-line bg-white p-6 shadow-card sm:p-8"
        onSubmit={handleSubmit}
      >
        <div className="space-y-2 text-center sm:text-left">
          <p className="text-lg leading-8 text-subtle">
            Analiza los recursos de un aula online o de un paquete IMSCC.
          </p>
          {tokenStatusError ? (
            <p
              aria-live="polite"
              className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-[#8a5a00]"
              role="status"
            >
              {tokenStatusError} El modo offline sigue disponible.
            </p>
          ) : null}
        </div>

        <fieldset className="space-y-4 text-left">
          <legend className="text-base font-semibold text-ink">
            Elige cómo quieres empezar
          </legend>

          <div className="grid gap-4 sm:grid-cols-2">
            {MODE_OPTIONS.map((option) => {
              const inputId = `analysis-mode-${option.mode}`;
              const descriptionId = `mode-${option.mode}-description`;
              const isSelected = selectedMode === option.mode;

              return (
                <label
                  key={option.mode}
                  className={classNames(
                    'choice-panel cursor-pointer',
                    isSelected && 'choice-panel-selected',
                  )}
                  htmlFor={inputId}
                >
                  <span className="grid grid-cols-[auto_1fr] items-start gap-4">
                    <input
                      aria-describedby={descriptionId}
                      checked={isSelected}
                      className="mt-1 h-5 w-5 accent-[#0f766e]"
                      id={inputId}
                      name="analysis-mode"
                      onChange={() => handleModeChange(option.mode)}
                      type="radio"
                      value={option.mode}
                    />

                    <span className="space-y-2">
                      <span className="block text-lg font-semibold text-ink">
                        {option.label}
                      </span>
                      <span
                        className="block text-sm leading-6 text-subtle"
                        id={descriptionId}
                      >
                        {option.description}
                      </span>
                      {option.mode === 'online' && !tokenActive ? (
                        <span className="block text-sm font-semibold leading-6 text-[#8a5a00]">
                          Requiere configurar un token de acceso antes de cargar
                          cursos.
                        </span>
                      ) : null}
                    </span>
                  </span>
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
