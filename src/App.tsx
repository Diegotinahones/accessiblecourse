import { useEffect, useState } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { LayoutSimple } from './components/LayoutSimple';
import { ApiError, api } from './lib/api';
import type { TokenStatus } from './lib/types';
import { AnalyzingPage } from './pages/AnalyzingPage';
import { LandingPage } from './pages/LandingPage';
import { OnlineTokenRequiredPage } from './pages/OnlineTokenRequiredPage';
import { OnlinePage } from './pages/OnlinePage';
import { ReportPage } from './pages/ReportPage';
import { ResourcesPage } from './pages/ResourcesPage';
import { TokenConfigurePage } from './pages/TokenConfigurePage';
import { TokenManagementPage } from './pages/TokenManagementPage';
import { TokenWelcomePage } from './pages/TokenWelcomePage';
import { UploadPage } from './pages/UploadPage';

const EMPTY_TOKEN_STATUS: TokenStatus = {
  demoTokenAvailable: false,
  mode: 'none',
  tokenActive: false,
  tokenConfigured: false,
};

function getConfigureTokenErrorMessage(caughtError: unknown) {
  if (
    caughtError instanceof ApiError &&
    caughtError.message.includes('invalid_canvas_token')
  ) {
    return 'No hemos podido validar el token. Revisa que sea correcto y siga vigente.';
  }

  if (
    caughtError instanceof Error &&
    caughtError.message.includes('invalid_canvas_token')
  ) {
    return 'No hemos podido validar el token. Revisa que sea correcto y siga vigente.';
  }

  return caughtError instanceof Error
    ? caughtError.message
    : 'No hemos podido guardar el token de acceso.';
}

export default function App() {
  const [tokenStatus, setTokenStatus] =
    useState<TokenStatus>(EMPTY_TOKEN_STATUS);
  const [isCheckingToken, setIsCheckingToken] = useState(true);
  const [tokenStatusError, setTokenStatusError] = useState<string | null>(null);
  const [tokenActionError, setTokenActionError] = useState<string | null>(null);
  const [isTokenActionPending, setIsTokenActionPending] = useState(false);
  const [hasContinuedWithoutToken, setHasContinuedWithoutToken] =
    useState(false);

  useEffect(() => {
    let active = true;

    async function loadTokenStatus() {
      try {
        setIsCheckingToken(true);
        const status = await api.getTokenStatus();
        if (!active) {
          return;
        }

        setTokenStatus(status);
        setTokenStatusError(null);
        setHasContinuedWithoutToken(status.tokenConfigured);
      } catch {
        if (!active) {
          return;
        }

        setTokenStatus(EMPTY_TOKEN_STATUS);
        setTokenStatusError('No se ha podido comprobar el estado del token.');
      } finally {
        if (active) {
          setIsCheckingToken(false);
        }
      }
    }

    void loadTokenStatus();

    return () => {
      active = false;
    };
  }, []);

  const handleActivateDemoToken = async () => {
    try {
      setIsTokenActionPending(true);
      setTokenActionError(null);
      const status = await api.activateDemoToken();
      if (!status.tokenActive) {
        setTokenActionError(
          'No se ha podido activar el token demo. Revisa que esté configurado en el backend.',
        );
        return false;
      }
      setTokenStatus(status);
      setTokenStatusError(null);
      setHasContinuedWithoutToken(status.tokenConfigured);
      return status.tokenActive;
    } catch (caughtError) {
      setTokenActionError(
        caughtError instanceof Error
          ? caughtError.message
          : 'No se ha podido configurar el token demo.',
      );
      return false;
    } finally {
      setIsTokenActionPending(false);
    }
  };

  const handleConfigureToken = async (token: string) => {
    try {
      setIsTokenActionPending(true);
      setTokenActionError(null);
      const status = await api.configureToken(token);
      if (!status.tokenActive) {
        setTokenActionError(
          'No hemos podido validar el token. Revisa que sea correcto y siga vigente.',
        );
        return false;
      }

      setTokenStatus(status);
      setTokenStatusError(null);
      setHasContinuedWithoutToken(status.tokenConfigured);
      return status.tokenActive;
    } catch (caughtError) {
      setTokenActionError(getConfigureTokenErrorMessage(caughtError));
      return false;
    } finally {
      setIsTokenActionPending(false);
    }
  };

  const handleDeactivateToken = async () => {
    try {
      setIsTokenActionPending(true);
      setTokenActionError(null);
      const status = await api.deactivateToken();
      setTokenStatus(status);
      setHasContinuedWithoutToken(false);
      return true;
    } catch (caughtError) {
      setTokenActionError(
        caughtError instanceof Error
          ? caughtError.message
          : 'No se ha podido eliminar el token de esta sesión.',
      );
      return false;
    } finally {
      setIsTokenActionPending(false);
    }
  };

  const handleContinueWithoutToken = () => {
    setTokenActionError(null);
    setHasContinuedWithoutToken(true);
  };

  if (isCheckingToken) {
    return (
      <LayoutSimple
        align="center"
        description="Comprobando si el modo online está disponible."
        showSkipLink={false}
        showTokenButton={false}
        title="Comprobando token de acceso"
        variant="plain"
      >
        <section className="mx-auto max-w-2xl rounded-3xl border border-line bg-white p-6 text-center text-sm leading-6 text-subtle shadow-card">
          Consultando el estado del token…
        </section>
      </LayoutSimple>
    );
  }

  const tokenActive = tokenStatus.tokenActive && tokenStatus.tokenConfigured;
  const shouldShowTokenWelcome =
    !tokenStatus.tokenConfigured && !hasContinuedWithoutToken;

  return (
    <Routes>
      <Route
        path="/"
        element={
          shouldShowTokenWelcome ? (
            <TokenWelcomePage
              actionError={tokenActionError}
              demoTokenAvailable={tokenStatus.demoTokenAvailable}
              isSubmitting={isTokenActionPending}
              onActivateDemo={handleActivateDemoToken}
              onContinueWithoutToken={handleContinueWithoutToken}
              statusError={tokenStatusError}
            />
          ) : (
            <LandingPage
              tokenActive={tokenActive}
              tokenConfigured={tokenStatus.tokenConfigured}
              tokenStatusError={tokenStatusError}
            />
          )
        }
      />
      <Route path="/offline" element={<UploadPage />} />
      <Route
        path="/online"
        element={
          tokenActive ? (
            <OnlinePage />
          ) : (
            <OnlineTokenRequiredPage
              actionError={tokenActionError}
              statusError={tokenStatusError}
            />
          )
        }
      />
      <Route
        path="/token/configure"
        element={
          <TokenConfigurePage
            actionError={tokenActionError}
            isSubmitting={isTokenActionPending}
            onConfigureToken={handleConfigureToken}
          />
        }
      />
      <Route
        path="/token"
        element={
          <TokenManagementPage
            actionError={tokenActionError}
            isSubmitting={isTokenActionPending}
            onActivateDemo={handleActivateDemoToken}
            onContinueWithoutToken={handleContinueWithoutToken}
            onDeactivateToken={handleDeactivateToken}
            statusError={tokenStatusError}
            tokenStatus={tokenStatus}
          />
        }
      />
      <Route path="/analyzing/:jobId" element={<AnalyzingPage />} />
      <Route path="/resources/:jobId" element={<ResourcesPage />} />
      <Route path="/report/:jobId" element={<ReportPage />} />
      <Route path="/jobs/:jobId/review" element={<ResourcesPage />} />
      <Route path="/jobs/:jobId/report" element={<ReportPage />} />
      <Route
        path="/upload"
        element={<Navigate replace to="/offline?mode=offline" />}
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
