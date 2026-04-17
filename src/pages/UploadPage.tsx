import { ChangeEvent, FormEvent, useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';
import { ProgressBar } from '../components/ProgressBar';
import { api } from '../lib/api';
import { formatFileSize, getModeSearch, rememberAppMode, rememberCourseName } from '../lib/utils';

export function UploadPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    rememberAppMode('offline');

    if (searchParams.get('mode') !== 'offline') {
      setSearchParams({ mode: 'offline' }, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    setSelectedFile(event.target.files?.[0] ?? null);
    setUploadProgress(0);
    setError(null);
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!selectedFile) {
      setError('Selecciona un archivo IMSCC o ZIP para continuar.');
      return;
    }

    try {
      setIsSubmitting(true);
      setUploadProgress(0);
      setError(null);
      const { jobId } = await api.createJob(selectedFile, {
        onProgress: (progress) => setUploadProgress(progress),
      });
      rememberCourseName(jobId, selectedFile.name);
      navigate(`/analyzing/${jobId}${getModeSearch('offline')}`);
    } catch (caughtError) {
      setError(
        caughtError instanceof Error ? caughtError.message : 'No hemos podido subir el curso.',
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <LayoutSimple
      align="center"
      backLabel="Cambiar modo"
      backTo="/?mode=offline"
      description="Sube un paquete IMSCC o ZIP y generaremos el inventario para revisar la accesibilidad del curso."
      title="Offline (IMSCC)"
    >
      <form
        className="card-panel mx-auto max-w-xl space-y-5 p-6 sm:p-8"
        onSubmit={handleSubmit}
      >
        <div className="space-y-2">
          <label className="block text-sm font-semibold text-ink" htmlFor="course-file">
            Selecciona archivo IMSCC o ZIP
          </label>
          <input
            accept=".imscc,.zip"
            className="field-input"
            disabled={isSubmitting}
            id="course-file"
            onChange={handleFileChange}
            type="file"
          />
        </div>

        <p aria-live="polite" className="min-h-[1.5rem] text-sm text-subtle">
          {selectedFile ? `${selectedFile.name} · ${formatFileSize(selectedFile.size)}` : ' '}
        </p>

        {error ? (
          <p
            aria-live="assertive"
            className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-danger"
            role="alert"
          >
            {error}
          </p>
        ) : null}

        {isSubmitting ? (
          <div className="space-y-3 rounded-2xl border border-line bg-[#f6f7f2] px-4 py-4">
            <ProgressBar label="Progreso de la subida" value={uploadProgress} />
            <p aria-live="polite" className="text-sm text-subtle">
              {uploadProgress >= 100
                ? 'Subida completada. Preparando el análisis…'
                : `Subiendo archivo… ${uploadProgress}%`}
            </p>
          </div>
        ) : null}

        <button
          className="button-primary w-full"
          disabled={!selectedFile || isSubmitting}
          type="submit"
        >
          {isSubmitting ? 'Subiendo curso…' : 'Subir curso'}
        </button>
      </form>
    </LayoutSimple>
  );
}
