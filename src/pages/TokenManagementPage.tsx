import { useEffect, useRef, useState } from 'react';
import { LayoutSimple } from '../components/LayoutSimple';
import { TokenWelcomePage } from './TokenWelcomePage';

interface TokenManagementPageProps {
  actionError: string | null;
  isSubmitting: boolean;
  onActivateDemo: () => Promise<boolean>;
  onContinueWithoutToken: () => void;
  onDeactivateToken: () => Promise<boolean>;
  statusError: string | null;
  tokenActive: boolean;
}

export function TokenManagementPage({
  actionError,
  isSubmitting,
  onActivateDemo,
  onContinueWithoutToken,
  onDeactivateToken,
  statusError,
  tokenActive,
}: TokenManagementPageProps) {
  const [isConfirmingRemoval, setIsConfirmingRemoval] = useState(false);
  const confirmationHeadingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (isConfirmingRemoval) {
      confirmationHeadingRef.current?.focus();
    }
  }, [isConfirmingRemoval]);

  if (!tokenActive) {
    return (
      <TokenWelcomePage
        actionError={actionError}
        isSubmitting={isSubmitting}
        onActivateDemo={onActivateDemo}
        onContinueWithoutToken={onContinueWithoutToken}
        statusError={statusError}
      />
    );
  }

  return (
    <LayoutSimple
      backLabel="Volver al inicio"
      backTo="/"
      description="AccessibleCourse puede consultar los cursos de Canvas a los que tienes acceso."
      title="Token de acceso configurado"
    >
      <section className="mx-auto max-w-3xl space-y-6 rounded-3xl border border-line bg-white p-6 shadow-card sm:p-8">
        <p className="text-base leading-7 text-subtle">
          El token está activo en esta sesión. No se muestra ni se pega en el
          frontend; la gestión se realiza desde el backend.
        </p>

        {actionError ? (
          <p
            aria-live="polite"
            className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm leading-6 text-danger"
            role="alert"
          >
            {actionError}
          </p>
        ) : null}

        {!isConfirmingRemoval ? (
          <button
            className="button-secondary w-full sm:w-auto"
            disabled={isSubmitting}
            onClick={() => setIsConfirmingRemoval(true)}
            type="button"
          >
            Eliminar token de esta sesión
          </button>
        ) : (
          <section
            aria-labelledby="confirm-token-removal-title"
            className="space-y-4 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-left"
            role="alertdialog"
          >
            <h2
              className="text-base font-semibold text-ink"
              id="confirm-token-removal-title"
              ref={confirmationHeadingRef}
              tabIndex={-1}
            >
              Confirmar eliminación del token
            </h2>
            <p className="text-sm leading-6 text-[#8a5a00]">
              Si eliminas el token de esta sesión, no podremos acceder a tus
              cursos matriculados desde el modo online.
            </p>
            <div className="flex flex-col gap-3 sm:flex-row">
              <button
                className="button-secondary w-full sm:w-auto"
                disabled={isSubmitting}
                onClick={() => setIsConfirmingRemoval(false)}
                type="button"
              >
                Cancelar
              </button>
              <button
                className="button-primary w-full sm:w-auto"
                disabled={isSubmitting}
                onClick={() => {
                  void onDeactivateToken().then((success) => {
                    if (success) {
                      setIsConfirmingRemoval(false);
                    }
                  });
                }}
                type="button"
              >
                {isSubmitting ? 'Eliminando token…' : 'Eliminar token'}
              </button>
            </div>
          </section>
        )}
      </section>
    </LayoutSimple>
  );
}
