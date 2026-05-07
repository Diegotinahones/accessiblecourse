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
      showSkipLink={false}
      showTokenButton={false}
      title="Bienvenido a AccessibleCourse"
      useMainLandmark={false}
      variant="plain"
    >
      <section className="mx-auto max-w-3xl space-y-7 rounded-2xl border border-line bg-white p-6 shadow-card sm:p-8">
        <div className="mx-auto max-w-2xl text-left">
          <p className="text-lg leading-8 text-ink">
            Configura un token para que podamos acceder a los cursos de Canvas
            que tengas disponibles. Si no dispones de ningún token de acceso,
            puedes continuar con el modo offline.
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

        <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:justify-center">
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
