import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { InventoryStatusBadge, ReviewStateBadge, SessionStatusBadge } from '../components/StatusBadge';
import { LayoutSimple } from '../components/LayoutSimple';
import {
  fetchChecklistTemplates,
  fetchResourceDetail,
  fetchResources,
  saveChecklist,
} from '../lib/api';
import type {
  ResourceDetailResponse,
  ResourceListItem,
  ReviewChecklistItem,
  ReviewSession,
} from '../lib/types';
import {
  formatDate,
  getReviewResourceTypeLabel,
  sortResourcesByPriority,
} from '../lib/types';

type SaveState = 'idle' | 'pending' | 'saving' | 'saved' | 'error';

const DEFAULT_JOB_ID = 'demo-accessible-course';

const RESPONSE_OPTIONS: Array<{ label: string; value: ReviewChecklistItem['value'] }> = [
  { label: 'Pendiente', value: 'PENDING' },
  { label: 'Cumple', value: 'PASS' },
  { label: 'No cumple', value: 'FAIL' },
];

function getSaveMessage(saveState: SaveState): string {
  switch (saveState) {
    case 'pending':
      return 'Cambios pendientes de guardar';
    case 'saving':
      return 'Guardando checklist en la API...';
    case 'saved':
      return 'Checklist guardado';
    case 'error':
      return 'No se pudo guardar el checklist';
    default:
      return 'Sin cambios pendientes';
  }
}

export function ResourcesPage() {
  const params = useParams<{ jobId: string }>();
  const jobId = params.jobId ?? DEFAULT_JOB_ID;
  const [resources, setResources] = useState<ResourceListItem[]>([]);
  const [selectedResourceId, setSelectedResourceId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ResourceDetailResponse | null>(null);
  const [reviewSession, setReviewSession] = useState<ReviewSession | null>(null);
  const [templateCount, setTemplateCount] = useState(0);
  const [loadingResources, setLoadingResources] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [screenError, setScreenError] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isDirty, setIsDirty] = useState(false);
  const [draftVersion, setDraftVersion] = useState(0);
  const draftVersionRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    setLoadingResources(true);
    setScreenError(null);

    Promise.all([fetchResources(jobId), fetchChecklistTemplates()])
      .then(([resourcePayload, templatePayload]) => {
        if (cancelled) {
          return;
        }

        const orderedResources = sortResourcesByPriority(resourcePayload.resources);
        setResources(orderedResources);
        setTemplateCount(Object.keys(templatePayload.templates).length);
        setReviewSession(resourcePayload.reviewSession);
        setSelectedResourceId((current) => {
          if (current && orderedResources.some((resource) => resource.id === current)) {
            return current;
          }

          return orderedResources[0]?.id ?? null;
        });
      })
      .catch((error: Error) => {
        if (!cancelled) {
          setScreenError(error.message);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingResources(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [jobId]);

  useEffect(() => {
    if (!selectedResourceId) {
      setDetail(null);
      return;
    }

    let cancelled = false;
    setLoadingDetail(true);
    setSaveState('idle');
    setSaveError(null);

    fetchResourceDetail(jobId, selectedResourceId)
      .then((payload) => {
        if (cancelled) {
          return;
        }

        setDetail(payload);
        setReviewSession(payload.reviewSession);
        setIsDirty(false);
        draftVersionRef.current = 0;
        setDraftVersion(0);
      })
      .catch((error: Error) => {
        if (!cancelled) {
          setScreenError(error.message);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingDetail(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [jobId, selectedResourceId]);

  async function persistDraft(versionAtSave: number, draft = detail) {
    if (!draft) {
      return;
    }

    const payload = {
      responses: draft.checklist.items.map((item) => ({
        itemKey: item.itemKey,
        value: item.value,
        ...(item.comment?.trim() ? { comment: item.comment.trim() } : {}),
      })),
    };

    setSaveState('saving');
    setSaveError(null);

    try {
      const result = await saveChecklist(jobId, draft.resource.id, payload);
      const refreshedResources = await fetchResources(jobId);
      const orderedResources = sortResourcesByPriority(refreshedResources.resources);

      setResources(orderedResources);
      setReviewSession(refreshedResources.reviewSession);
      setDetail((current) => {
        if (!current || current.resource.id !== result.resourceId) {
          return current;
        }

        return {
          ...current,
          reviewSession: refreshedResources.reviewSession,
          resource: {
            ...current.resource,
            reviewState: result.reviewState,
            failCount: result.failCount,
            updatedAt: result.updatedAt,
          },
        };
      });

      if (draftVersionRef.current === versionAtSave) {
        setIsDirty(false);
        setSaveState('saved');
      } else {
        setSaveState('pending');
      }
    } catch (error) {
      setSaveState('error');
      setSaveError(error instanceof Error ? error.message : 'No se pudo guardar el checklist.');
    }
  }

  useEffect(() => {
    if (!detail || !isDirty) {
      return;
    }

    const versionAtSave = draftVersion;
    const snapshot = detail;
    const timeoutId = window.setTimeout(() => {
      void persistDraft(versionAtSave, snapshot);
    }, 700);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [detail, draftVersion, isDirty]);

  function updateChecklistItem(itemKey: string, updater: (item: ReviewChecklistItem) => ReviewChecklistItem) {
    setDetail((current) => {
      if (!current) {
        return current;
      }

      return {
        ...current,
        checklist: {
          ...current.checklist,
          items: current.checklist.items.map((item) => (item.itemKey === itemKey ? updater(item) : item)),
        },
      };
    });

    setSaveState('pending');
    setSaveError(null);
    setIsDirty(true);
    draftVersionRef.current += 1;
    setDraftVersion(draftVersionRef.current);
  }

  function handleSelectResource(resourceId: string) {
    if (detail && isDirty && saveState !== 'saving') {
      void persistDraft(draftVersionRef.current, detail);
    }

    setSelectedResourceId(resourceId);
  }

  function handleRetrySave() {
    draftVersionRef.current += 1;
    setDraftVersion(draftVersionRef.current);
    setSaveState('pending');
    setSaveError(null);
    setIsDirty(true);
  }

  return (
    <LayoutSimple
      title="Recursos y checklist"
      description="Cada criterio del profesorado se guarda en la API y recalcula el estado del recurso para priorizar la revisión."
      footer={
        <div className="card-panel flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-subtle">Siguiente paso</p>
            <p className="mt-2 text-sm text-subtle">
              Abre el informe para ver los incumplimientos agrupados por recurso con sus recomendaciones.
            </p>
          </div>
          <Link className="button-primary" to={`/jobs/${jobId}/report`}>
            Ir al informe
          </Link>
        </div>
      }
    >
      <section className="card-panel mb-6 grid gap-5 p-6 lg:grid-cols-[minmax(0,1fr),auto] lg:items-start">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.16em] text-subtle">Pantalla 3</p>
          <h2 className="mt-2 text-2xl font-semibold text-ink">Checklist persistido por recurso</h2>
          <p className="mt-3 max-w-3xl text-sm leading-7 text-subtle">
            Al abrir un recurso se lee su detalle desde la base de datos. Cada cambio se guarda con debounce y el badge se
            actualiza automáticamente a “OK”, “En revisión” o “Requiere cambios”.
          </p>
        </div>

        <div className="grid gap-4 rounded-2xl border border-line bg-panel p-4 sm:grid-cols-2">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-subtle">Plantillas activas</p>
            <p className="mt-2 text-2xl font-semibold text-ink">{templateCount}</p>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-subtle">Sesión</p>
            <div className="mt-2">
              {reviewSession ? (
                <SessionStatusBadge status={reviewSession.status} />
              ) : (
                <span className="inline-flex rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-sm font-semibold text-slate-600">
                  Cargando
                </span>
              )}
            </div>
          </div>
        </div>
      </section>

      {screenError ? (
        <div aria-live="assertive" className="mb-6 rounded-2xl border border-rose-200 bg-rose-50 p-5 text-danger" role="alert">
          {screenError}
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[minmax(260px,320px),minmax(0,1fr)]">
        <aside className="card-panel p-5">
          <div className="mb-4">
            <p className="text-sm font-semibold uppercase tracking-[0.16em] text-subtle">Recursos</p>
            <h2 className="mt-2 text-xl font-semibold text-ink">Prioridad de revisión</h2>
            <p className="mt-2 text-sm text-subtle">Ordenados por recursos con cambios requeridos, en revisión y resueltos.</p>
          </div>

          {loadingResources ? (
            <div className="rounded-2xl border border-line bg-panel p-4 text-sm text-subtle">Cargando inventario real...</div>
          ) : resources.length === 0 ? (
            <div className="rounded-2xl border border-line bg-panel p-4 text-sm text-subtle">No hay recursos disponibles.</div>
          ) : (
            <div className="space-y-3">
              {resources.map((resource) => (
                <button
                  key={resource.id}
                  type="button"
                  onClick={() => handleSelectResource(resource.id)}
                  className={`w-full rounded-2xl border p-4 text-left transition ${
                    resource.id === selectedResourceId
                      ? 'border-slate-900 bg-slate-50 shadow-sm'
                      : 'border-line bg-white hover:border-slate-300 hover:bg-slate-50'
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <span className="text-xs font-semibold uppercase tracking-[0.16em] text-subtle">
                      {getReviewResourceTypeLabel(resource.type)}
                    </span>
                    <ReviewStateBadge state={resource.reviewState} />
                  </div>
                  <p className="mt-3 text-base font-semibold text-ink">{resource.title}</p>
                  <p className="mt-2 text-sm leading-6 text-subtle">
                    {resource.coursePath ?? resource.path ?? 'Ruta no disponible'}
                  </p>
                  <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-subtle">
                    <span>{resource.failCount} FAIL</span>
                    <span>{formatDate(resource.updatedAt)}</span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </aside>

        <section className="card-panel p-6">
          {loadingResources || loadingDetail ? (
            <div className="rounded-2xl border border-line bg-panel p-6 text-sm text-subtle">Cargando detalle del recurso...</div>
          ) : !detail ? (
            <div className="rounded-2xl border border-line bg-panel p-6 text-sm text-subtle">
              Selecciona un recurso para revisar su checklist.
            </div>
          ) : (
            <div className="space-y-6">
              <header className="flex flex-col gap-4 border-b border-line pb-5 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <p className="text-sm font-semibold uppercase tracking-[0.16em] text-subtle">
                    {getReviewResourceTypeLabel(detail.resource.type)}
                  </p>
                  <h2 className="mt-2 text-2xl font-semibold text-ink">{detail.resource.title}</h2>
                  <p className="mt-2 text-sm leading-7 text-subtle">
                    {detail.resource.coursePath ?? detail.resource.path ?? 'Sin ruta disponible'}
                  </p>
                </div>

                <div className="flex flex-wrap gap-2">
                  <ReviewStateBadge state={detail.resource.reviewState} />
                  <InventoryStatusBadge status={detail.resource.status} />
                </div>
              </header>

              <div className="grid gap-4 sm:grid-cols-3">
                <div className="rounded-2xl border border-line bg-panel p-4">
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-subtle">Origen</p>
                  <p className="mt-2 text-sm font-semibold text-ink">{detail.resource.origin ?? 'No indicado'}</p>
                </div>
                <div className="rounded-2xl border border-line bg-panel p-4">
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-subtle">Sesión</p>
                  <div className="mt-2">
                    {reviewSession ? <SessionStatusBadge status={reviewSession.status} /> : <span>Sin sesión</span>}
                  </div>
                </div>
                <div className="rounded-2xl border border-line bg-panel p-4">
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-subtle">Actualizado</p>
                  <p className="mt-2 text-sm font-semibold text-ink">{formatDate(detail.resource.updatedAt)}</p>
                </div>
              </div>

              {detail.resource.url ? (
                <a
                  className="inline-flex text-sm font-semibold text-ink underline underline-offset-4"
                  href={detail.resource.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Abrir recurso original
                </a>
              ) : null}

              {detail.resource.notes ? (
                <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-slate-700">
                  {detail.resource.notes}
                </div>
              ) : null}

              <div className="flex flex-col gap-3 rounded-2xl border border-line bg-panel p-4 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-sm font-semibold text-ink">{getSaveMessage(saveState)}</p>
                {saveState === 'error' ? (
                  <button type="button" className="button-secondary" onClick={handleRetrySave}>
                    Reintentar guardado
                  </button>
                ) : null}
              </div>

              {saveError ? (
                <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-danger">{saveError}</div>
              ) : null}

              <div className="space-y-4">
                {detail.checklist.items.map((item) => (
                  <article key={item.itemKey} className="rounded-2xl border border-line bg-white p-5">
                    <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                      <div>
                        <h3 className="text-lg font-semibold text-ink">{item.label}</h3>
                        {item.description ? <p className="mt-2 text-sm leading-7 text-subtle">{item.description}</p> : null}
                      </div>
                      <span
                        className={`inline-flex rounded-full border px-3 py-1 text-sm font-semibold ${
                          item.value === 'PASS'
                            ? 'border-emerald-200 bg-emerald-50 text-success'
                            : item.value === 'FAIL'
                              ? 'border-rose-200 bg-rose-50 text-danger'
                              : 'border-slate-200 bg-slate-50 text-slate-600'
                        }`}
                      >
                        {item.value === 'PASS' ? 'Cumple' : item.value === 'FAIL' ? 'No cumple' : 'Pendiente'}
                      </span>
                    </div>

                    <div className="mt-4 grid gap-2 sm:grid-cols-3">
                      {RESPONSE_OPTIONS.map((option) => (
                        <button
                          key={option.value}
                          type="button"
                          aria-pressed={item.value === option.value}
                          onClick={() => updateChecklistItem(item.itemKey, (current) => ({ ...current, value: option.value }))}
                          className={`rounded-xl border px-4 py-3 text-sm font-semibold transition ${
                            item.value === option.value
                              ? 'border-slate-900 bg-slate-900 text-white'
                              : 'border-line bg-white text-ink hover:border-slate-300 hover:bg-slate-50'
                          }`}
                        >
                          {option.label}
                        </button>
                      ))}
                    </div>

                    <label className="mt-4 block text-sm font-semibold text-ink" htmlFor={`comment-${item.itemKey}`}>
                      Comentario docente
                    </label>
                    <textarea
                      id={`comment-${item.itemKey}`}
                      className="mt-2 min-h-24 w-full rounded-2xl border border-line px-4 py-3 text-sm text-ink"
                      rows={3}
                      value={item.comment ?? ''}
                      placeholder="Añade contexto, evidencia o el motivo de la revisión."
                      onChange={(event) =>
                        updateChecklistItem(item.itemKey, (current) => ({ ...current, comment: event.target.value }))
                      }
                    />

                    <div
                      className={`mt-4 rounded-2xl border p-4 ${
                        item.value === 'FAIL'
                          ? 'border-rose-200 bg-rose-50'
                          : 'border-slate-200 bg-slate-50'
                      }`}
                    >
                      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-subtle">Recomendación para el informe</p>
                      <p className="mt-2 text-sm leading-7 text-slate-700">
                        {item.recommendation ?? 'Sin recomendación registrada para este criterio.'}
                      </p>
                    </div>
                  </article>
                ))}
              </div>
            </div>
          )}
        </section>
      </div>
    </LayoutSimple>
  );
}
