import { ChangeEvent, FormEvent, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';
import { api } from '../lib/api';
import { formatFileSize, rememberCourseName } from '../lib/utils';

export function UploadPage() {
  const navigate = useNavigate();
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    setSelectedFile(event.target.files?.[0] ?? null);
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
      setError(null);
      const { jobId } = await api.createJob(selectedFile);
      rememberCourseName(jobId, selectedFile.name);
      navigate(`/analyzing/${jobId}`);
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : 'No hemos podido subir el curso.',
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <LayoutSimple
      align="center"
      description="Haz tu curso accesible para todos"
      title="AccessibleCourse"
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
