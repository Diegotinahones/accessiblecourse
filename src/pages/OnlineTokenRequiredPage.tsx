import { useNavigate } from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';

interface OnlineTokenRequiredPageProps {
  actionError: string | null;
  statusError: string | null;
}

export function OnlineTokenRequiredPage({
  actionError,
  statusError,
}: OnlineTokenRequiredPageProps) {
  const navigate = useNavigate();

  return (
    <LayoutSimple
      align="center"
      backLabel="Cambiar modo"
      backTo="/?mode=online"
      description="El modo online necesita un token activo para consultar Canvas/UOC."
      showTokenButton={false}
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
            onClick={() => navigate('/token/configure')}
            type="button"
          >
            Configurar token
          </button>
          <button
            className="button-secondary w-full sm:w-auto"
            onClick={() => navigate('/offline?mode=offline')}
            type="button"
          >
            Usar modo offline
          </button>
        </div>
      </section>
    </LayoutSimple>
  );
}
