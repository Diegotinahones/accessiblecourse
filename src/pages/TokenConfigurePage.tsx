import { FormEvent, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';

interface TokenConfigurePageProps {
  actionError: string | null;
  isSubmitting: boolean;
  onConfigureToken: (token: string) => Promise<boolean>;
}

export function TokenConfigurePage({
  actionError,
  isSubmitting,
  onConfigureToken,
}: TokenConfigurePageProps) {
  const navigate = useNavigate();
  const [token, setToken] = useState('');
  const [showToken, setShowToken] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [hasSubmitted, setHasSubmitted] = useState(false);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const trimmedToken = token.trim();
    if (!trimmedToken) {
      setLocalError('Introduce un token de acceso de Canvas.');
      return;
    }

    setLocalError(null);
    setHasSubmitted(true);
    const success = await onConfigureToken(trimmedToken);
    setToken('');

    if (success) {
      navigate('/');
    }
  };

  return (
    <LayoutSimple
      align="center"
      backLabel="Volver"
      backTo="/"
      description="Introduce tu token de Canvas para que podamos acceder a tus cursos."
      showSkipLink={false}
      showTokenButton={false}
      title="Configura tu token"
      useMainLandmark={false}
    >
      <form
        className="mx-auto max-w-xl space-y-5 rounded-2xl border border-line bg-white p-6 text-left shadow-card sm:p-7"
        onSubmit={handleSubmit}
      >
        <div className="space-y-3">
          <label
            className="block text-base font-semibold text-ink"
            htmlFor="canvas-access-token"
          >
            Token de acceso de Canvas
          </label>
          <div className="relative">
            <input
              aria-describedby="canvas-token-help"
              autoComplete="off"
              className="field-input pr-36"
              disabled={isSubmitting}
              id="canvas-access-token"
              onChange={(event) => setToken(event.target.value)}
              type={showToken ? 'text' : 'password'}
              value={token}
            />
            <button
              className="absolute right-2 top-1/2 min-h-10 -translate-y-1/2 rounded-md px-3 text-sm font-semibold text-[var(--uoc-blue)] transition hover:bg-[var(--color-uoc-cyan-soft)]"
              disabled={isSubmitting}
              onClick={() => setShowToken((current) => !current)}
              type="button"
            >
              {showToken ? 'Ocultar' : 'Mostrar'}
            </button>
          </div>
          <p className="text-sm leading-6 text-subtle" id="canvas-token-help">
            No guardamos el token en este navegador.
          </p>
        </div>

        {localError ? (
          <p
            aria-live="polite"
            className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm leading-6 text-danger"
            role="alert"
          >
            {localError}
          </p>
        ) : null}

        {hasSubmitted && actionError ? (
          <p
            aria-live="polite"
            className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm leading-6 text-danger"
            role="alert"
          >
            {actionError}
          </p>
        ) : null}

        <div>
          <button
            className="button-primary w-full sm:w-auto"
            disabled={isSubmitting}
            type="submit"
          >
            {isSubmitting ? 'Guardando token…' : 'Continuar'}
          </button>
        </div>
      </form>
    </LayoutSimple>
  );
}
