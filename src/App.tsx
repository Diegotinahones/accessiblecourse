import { Navigate, Route, Routes } from 'react-router-dom';
import { AnalyzingPage } from './pages/AnalyzingPage';
import { ReportPage } from './pages/ReportPage';
import { ResourcesPage } from './pages/ResourcesPage';
import { UploadPage } from './pages/UploadPage';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<UploadPage />} />
      <Route path="/analyzing/:jobId" element={<AnalyzingPage />} />
      <Route path="/resources/:jobId" element={<ResourcesPage />} />
      <Route path="/report/:jobId" element={<ReportPage />} />
      <Route path="/jobs/:jobId/review" element={<ResourcesPage />} />
      <Route path="/jobs/:jobId/report" element={<ReportPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
