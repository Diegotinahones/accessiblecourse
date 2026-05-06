import { Link } from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';

interface OnlineTokenRequiredPageProps {
  actionError: string | null;
  isSubmitting: boolean;
  onActivateDemo: () => Promise<boolean>;
  statusError: string | null;
}

export function OnlineTokenRequiredPage({
  actionError,
  isSubmitting,
  onActivateDemo,
  statusError,
}: OnlineTokenRequiredPageProps) {
  return (
    <LayoutSimple
      align="center"
      backLabel="Cambiar modo"
      backTo="/?mode=online"
      description="El modo online necesita un token activo para consultar Canvas/UOC."
      title="Token necesario para el modo online"
    >
      <section className="mx-auto max-w-3xl space-y-6 rounded-3xl border border-line bg-white p-6 shadow-card sm:p-8">
        <p className="text-lg leading-8 text-ink">
          No podemos acceder a tus cursos online si no has configurado un token
          de acceso.
        </p>

        {statusError ? (
          <p
            aria-live="polite"
            className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-[#8a5a00]"
            role="status"
          >
            {statusError}
          </p>
        ) : null}

        {actionError ? (
          <p
            aria-live="polite"
            className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm leading-6 text-danger"
            role="alert"
          >
            {actionError}
          </p>
        ) : null}

        <div className="flex flex-col gap-3 sm:flex-row sm:justify-center">
          <button
            className="button-primary w-full sm:w-auto"
            disabled={isSubmitting}
            onClick={() => {
              void onActivateDemo();
            }}
            type="button"
          >
            {isSubmitting ? 'Configurando token…' : 'Configurar token'}
          </button>
          <Link
            className="button-secondary w-full sm:w-auto"
            to="/offline?mode=offline"
          >
            Usar modo offline
          </Link>
        </div>
      </section>
    </LayoutSimple>
  );
}
