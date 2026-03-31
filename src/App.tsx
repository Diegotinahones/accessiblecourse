import { Navigate, NavLink, Route, Routes, useParams } from 'react-router-dom';

import { ReportPage } from './pages/ReportPage';
import { ResourcesPage } from './pages/ResourcesPage';

const DEFAULT_JOB_ID = 'demo-accessible-course';

function Navigation({ jobId }: { jobId: string }) {
  return (
    <nav className="top-nav" aria-label="Navegación principal">
      <NavLink
        to={`/jobs/${jobId}/review`}
        className={({ isActive }) => `top-nav__link ${isActive ? 'top-nav__link--active' : ''}`}
      >
        Revisión
      </NavLink>
      <NavLink
        to={`/jobs/${jobId}/report`}
        className={({ isActive }) => `top-nav__link ${isActive ? 'top-nav__link--active' : ''}`}
      >
        Informe
      </NavLink>
    </nav>
  );
}

function ReviewRoute() {
  const params = useParams<{ jobId: string }>();
  const jobId = params.jobId ?? DEFAULT_JOB_ID;

  return (
    <>
      <Navigation jobId={jobId} />
      <ResourcesPage />
    </>
  );
}

function ReportRoute() {
  const params = useParams<{ jobId: string }>();
  const jobId = params.jobId ?? DEFAULT_JOB_ID;

  return (
    <>
      <Navigation jobId={jobId} />
      <ReportPage />
    </>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to={`/jobs/${DEFAULT_JOB_ID}/review`} replace />} />
      <Route path="/jobs/:jobId/review" element={<ReviewRoute />} />
      <Route path="/jobs/:jobId/report" element={<ReportRoute />} />
      <Route path="/resources/:jobId" element={<ReviewRoute />} />
      <Route path="/report/:jobId" element={<ReportRoute />} />
      <Route path="*" element={<Navigate to={`/jobs/${DEFAULT_JOB_ID}/review`} replace />} />
    </Routes>
  );
}
