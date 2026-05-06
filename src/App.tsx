import { useEffect, useState } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { LayoutSimple } from './components/LayoutSimple';
import { api } from './lib/api';
import { AnalyzingPage } from './pages/AnalyzingPage';
import { LandingPage } from './pages/LandingPage';
import { OnlineTokenRequiredPage } from './pages/OnlineTokenRequiredPage';
import { OnlinePage } from './pages/OnlinePage';
import { ReportPage } from './pages/ReportPage';
import { ResourcesPage } from './pages/ResourcesPage';
import { TokenManagementPage } from './pages/TokenManagementPage';
import { TokenWelcomePage } from './pages/TokenWelcomePage';
import { UploadPage } from './pages/UploadPage';

export default function App() {
  const [tokenActive, setTokenActive] = useState(false);
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

        setTokenActive(status.tokenActive);
        setTokenStatusError(null);
        setHasContinuedWithoutToken(status.tokenActive);
      } catch {
        if (!active) {
          return;
        }

        setTokenActive(false);
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
      setTokenActive(status.tokenActive);
      setTokenStatusError(null);
      setHasContinuedWithoutToken(status.tokenActive);
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

  const handleDeactivateToken = async () => {
    try {
      setIsTokenActionPending(true);
      setTokenActionError(null);
      await api.deactivateToken();
      setTokenActive(false);
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

  const shouldShowTokenWelcome = !tokenActive && !hasContinuedWithoutToken;

  return (
    <Routes>
      <Route
        path="/"
        element={
          shouldShowTokenWelcome ? (
            <TokenWelcomePage
              actionError={tokenActionError}
              isSubmitting={isTokenActionPending}
              onActivateDemo={handleActivateDemoToken}
              onContinueWithoutToken={handleContinueWithoutToken}
              statusError={tokenStatusError}
            />
          ) : (
            <LandingPage
              tokenActive={tokenActive}
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
              isSubmitting={isTokenActionPending}
              onActivateDemo={handleActivateDemoToken}
              statusError={tokenStatusError}
            />
          )
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
            tokenActive={tokenActive}
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
