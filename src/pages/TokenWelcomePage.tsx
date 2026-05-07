import { useNavigate } from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';

interface TokenWelcomePageProps {
  actionError: string | null;
  demoTokenAvailable: boolean;
  isSubmitting: boolean;
  onActivateDemo: () => Promise<boolean>;
  onContinueWithoutToken?: () => void;
  statusError?: string | null;
}

export function TokenWelcomePage({
  actionError,
  demoTokenAvailable,
  isSubmitting,
  onActivateDemo,
  onContinueWithoutToken,
  statusError,
}: TokenWelcomePageProps) {
  const navigate = useNavigate();

  return (
    <LayoutSimple
      align="center"
      description="Configura el acceso online o continúa con el modo offline."
      showSkipLink={false}
      showTokenButton={false}
      title="Bienvenido a AccessibleCourse"
      variant="plain"
    >
      <section className="mx-auto max-w-3xl space-y-6 rounded-3xl border border-line bg-white p-6 shadow-card sm:p-8">
        <div className="space-y-4 text-left">
          <p className="text-lg leading-8 text-ink">
            Configura tu token de acceso de Canvas para que podamos analizar los
            cursos a los que tienes acceso.
          </p>
          <p className="text-base leading-7 text-subtle">
            Si no dispones de token, puedes continuar usando el modo offline
            subiendo un archivo IMSCC o ZIP del curso.
          </p>
        </div>

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

          {demoTokenAvailable ? (
            <button
              className="button-secondary w-full sm:w-auto"
              disabled={isSubmitting}
              onClick={() => {
                void onActivateDemo();
              }}
              type="button"
            >
              {isSubmitting ? 'Activando demo…' : 'Usar token de demo'}
            </button>
          ) : null}

          {onContinueWithoutToken ? (
            <button
              className="button-secondary w-full sm:w-auto"
              onClick={onContinueWithoutToken}
              type="button"
            >
              Continuar sin token
            </button>
          ) : (
            <button
              className="button-secondary w-full sm:w-auto"
              onClick={() => navigate('/')}
              type="button"
            >
              Continuar sin token
            </button>
          )}
        </div>
      </section>
    </LayoutSimple>
  );
}
