import { useNavigate } from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';
import type { AppMode } from '../lib/types';
import { classNames, getModeRoute, rememberAppMode } from '../lib/utils';

interface ModeAction {
  mode: AppMode;
  label: string;
  summary: string;
}

const MODE_ACTIONS: ModeAction[] = [
  {
    mode: 'online',
    label: 'Online (Inicia sesión en la UOC)',
    summary: 'Conecta con Canvas/UOC y elige tu curso directamente desde la plataforma.',
  },
  {
    mode: 'offline',
    label: 'Offline (Sube tu archivo IMSCC)',
    summary: 'Carga un paquete IMSCC o ZIP exportado y empieza el análisis al momento.',
  },
];

export function LandingPage() {
  const navigate = useNavigate();

  function handleStart(mode: AppMode) {
    rememberAppMode(mode);
    navigate(getModeRoute(mode));
  }

  return (
    <LayoutSimple
      align="center"
      description="Empieza directamente en el flujo que prefieras."
      title="Haz tu curso accesible"
    >
      <section className="card-panel mx-auto max-w-3xl space-y-4 p-6 sm:p-8">
        <p className="text-sm leading-6 text-subtle">
          Elige cómo quieres trabajar hoy. No hace falta continuar en un segundo paso.
        </p>

        <div className="grid gap-4">
          {MODE_ACTIONS.map((action) => (
            <button
              key={action.mode}
              className={classNames(
                'rounded-3xl border border-line bg-white p-5 text-left transition hover:border-[#8da793] hover:bg-[#f6f7f2] sm:p-6',
                action.mode === 'online' && 'border-[#7fa388] bg-[#f4f7f1]',
              )}
              onClick={() => handleStart(action.mode)}
              type="button"
            >
              <span className="block text-xl font-semibold text-ink">{action.label}</span>
              <span className="mt-2 block text-sm leading-6 text-subtle">{action.summary}</span>
            </button>
          ))}
        </div>
      </section>
    </LayoutSimple>
  );
}
