import { ChangeEvent, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';
import { api } from '../lib/api';
import { formatFileSize } from '../lib/utils';

export function UploadPage() {
  const navigate = useNavigate();
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;
    setSelectedFile(file);
    setError(null);
  };

  const handleContinue = async () => {
    if (!selectedFile) {
      return;
    }

    try {
      setIsSubmitting(true);
      const { jobId } = await api.createJob(selectedFile);
      navigate(`/analyzing/${jobId}`);
    } catch (caughtError) {
      const message = caughtError instanceof Error ? caughtError.message : 'No hemos podido iniciar el analisis.';
      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <LayoutSimple
      description="Haz tu asignatura accesible para todos con una revision inicial del paquete IMSCC."
      title="Subir curso"
    >
      <div className="mx-auto max-w-2xl">
        <section aria-labelledby="subir-curso" className="card-panel p-8 sm:p-10">
          <h2 id="subir-curso" className="text-2xl font-semibold text-ink">
            Subir curso
          </h2>
          <p className="mt-3 text-base leading-7 text-subtle">
            Selecciona un archivo `.imscc` o `.zip` para comenzar el analisis.
          </p>

          <div className="mt-8 space-y-5">
            <div>
              <label className="button-primary w-full cursor-pointer sm:w-auto" htmlFor="course-file">
                Subir curso
              </label>
              <input
                accept=".imscc,.zip"
                className="sr-only"
                id="course-file"
                onChange={handleFileChange}
                type="file"
              />
            </div>

            <div
              aria-live="polite"
              className="min-h-[4.5rem] rounded-2xl border border-dashed border-line bg-panel p-4"
            >
              {selectedFile ? (
                <div className="space-y-1">
                  <p className="text-base font-semibold text-ink">{selectedFile.name}</p>
                  <p className="text-sm text-subtle">{formatFileSize(selectedFile.size)}</p>
                </div>
              ) : (
                <p className="text-sm text-subtle">Aun no has seleccionado ningun archivo.</p>
              )}
            </div>

            {error ? (
              <div aria-live="assertive" className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-danger">
                {error}
              </div>
            ) : null}

            <button
              className="button-secondary w-full sm:w-auto"
              disabled={!selectedFile || isSubmitting}
              onClick={handleContinue}
              type="button"
            >
              {isSubmitting ? 'Creando analisis...' : 'Continuar'}
            </button>
          </div>
        </section>
      </div>
    </LayoutSimple>
  );
}
