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
      backLabel="Cancelar"
      backTo="/"
      description="Introduce tu token personal de Canvas/UOC."
      showTokenButton={false}
      title="Configurar token de Canvas"
    >
      <form
        className="mx-auto max-w-2xl space-y-6 rounded-3xl border border-line bg-white p-6 text-left shadow-card sm:p-8"
        onSubmit={handleSubmit}
      >
        <div className="space-y-3">
          <label
            className="block text-base font-semibold text-ink"
            htmlFor="canvas-access-token"
          >
            Token de acceso de Canvas
          </label>
          <div className="flex flex-col gap-3 sm:flex-row">
            <input
              aria-describedby="canvas-token-help"
              autoComplete="off"
              className="field-input"
              disabled={isSubmitting}
              id="canvas-access-token"
              onChange={(event) => setToken(event.target.value)}
              type={showToken ? 'text' : 'password'}
              value={token}
            />
            <button
              className="button-secondary shrink-0"
              disabled={isSubmitting}
              onClick={() => setShowToken((current) => !current)}
              type="button"
            >
              {showToken ? 'Ocultar token' : 'Mostrar token'}
            </button>
          </div>
          <p className="text-sm leading-6 text-subtle" id="canvas-token-help">
            El token se enviará al servidor por HTTPS, se validará con
            Canvas/UOC y se guardará cifrado. No se mostrará de nuevo.
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

        <div className="flex flex-col gap-3 sm:flex-row">
          <button
            className="button-primary w-full sm:w-auto"
            disabled={isSubmitting}
            type="submit"
          >
            {isSubmitting ? 'Guardando token…' : 'Guardar token'}
          </button>
          <button
            className="button-secondary w-full sm:w-auto"
            disabled={isSubmitting}
            onClick={() => navigate('/')}
            type="button"
          >
            Cancelar
          </button>
        </div>
      </form>
    </LayoutSimple>
  );
}
