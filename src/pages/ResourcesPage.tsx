import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { LayoutSimple } from '../components/LayoutSimple';
import { InventoryStatusBadge, ReviewStateBadge, SessionStatusBadge } from '../components/StatusBadge';
import { fetchChecklistTemplates, fetchResourceDetail, fetchResources, saveChecklist } from '../lib/api';
import type {
  ChecklistItem,
  ResourceDetailResponse,
  ResourceListItem,
  ReviewSession,
} from '../lib/types';
import {
  formatDate,
  getResourceTypeLabel,
  sortResourcesByPriority,
} from '../lib/types';

type SaveState = 'idle' | 'pending' | 'saving' | 'saved' | 'error';

const DEFAULT_JOB_ID = 'demo-accessible-course';

const RESPONSE_OPTIONS: Array<{ label: string; value: ChecklistItem['value'] }> = [
  { label: 'Pendiente', value: 'PENDING' },
  { label: 'Cumple', value: 'PASS' },
  { label: 'No cumple', value: 'FAIL' },
];

function getSaveMessage(saveState: SaveState): string {
  switch (saveState) {
    case 'pending':
      return 'Cambios pendientes de guardar';
    case 'saving':
      return 'Guardando checklist...';
    case 'saved':
      return 'Checklist guardado';
    case 'error':
      return 'No se pudo guardar en la API';
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
  const [templateCount, setTemplateCount] = useState(0);
  const [reviewSession, setReviewSession] = useState<ReviewSession | null>(null);
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

  async function persistDraft(versionAtSave: number) {
    if (!detail) {
      return;
    }

    const payload = {
      responses: detail.checklist.items.map((item) => ({
        itemKey: item.itemKey,
        value: item.value,
        ...(item.comment?.trim() ? { comment: item.comment.trim() } : {}),
      })),
    };

    setSaveState('saving');
    setSaveError(null);

    try {
      const result = await saveChecklist(jobId, detail.resource.id, payload);
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
    const timeoutId = window.setTimeout(() => {
      void persistDraft(versionAtSave);
    }, 700);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [detail, draftVersion, isDirty]);

  function updateChecklistItem(itemKey: string, updater: (item: ChecklistItem) => ChecklistItem) {
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
      description="La revisión docente ya persiste en la base de datos. Cada recurso muestra su estado real y se recalcula automáticamente al guardar."
      footer={
        <div className="panel summary-footer">
          <div>
            <span className="detail-meta__label">Siguiente paso</span>
            <strong>Abre el informe para ver los FAIL agrupados por recurso.</strong>
          </div>
          <Link className="primary-button" to={`/jobs/${jobId}/report`}>
            Ir al informe
          </Link>
        </div>
      }
    >
      <section className="panel panel--hero">
        <div>
          <p className="eyebrow">Pantalla 3</p>
          <h2>Checklist persistido por recurso</h2>
          <p>
            Cada cambio se guarda con debounce en la API y actualiza el estado del recurso para priorizar el trabajo pendiente.
          </p>
        </div>
        <div className="hero__meta">
          <div>
            <span className="detail-meta__label">Plantillas activas</span>
            <strong>{templateCount}</strong>
          </div>
          <div>
            <span className="detail-meta__label">Sesión</span>
            {reviewSession ? (
              <SessionStatusBadge status={reviewSession.status} />
            ) : (
              <span className="status-badge status-badge--neutral">Cargando</span>
            )}
          </div>
        </div>
      </section>

      {screenError ? <p className="error-banner">{screenError}</p> : null}

      <div className="review-layout">
        <aside className="panel sidebar">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Recursos</p>
              <h2>Prioridad de revisión</h2>
            </div>
            <p className="sidebar__hint">Ordenados por “requiere cambios”, “en revisión” y “ok”.</p>
          </div>

          <div className="resource-list" role="list">
            {resources.map((resource) => (
              <button
                key={resource.id}
                type="button"
                className={`resource-card ${resource.id === selectedResourceId ? 'resource-card--active' : ''}`}
                onClick={() => setSelectedResourceId(resource.id)}
              >
                <div className="resource-card__top">
                  <span className="resource-type">{getResourceTypeLabel(resource.type)}</span>
                  <ReviewStateBadge state={resource.reviewState} />
                </div>
                <strong>{resource.title}</strong>
                <p>{resource.coursePath ?? resource.path ?? 'Ruta no disponible'}</p>
                <div className="resource-card__meta">
                  <span>{resource.failCount} incumplimientos</span>
                  <span>{formatDate(resource.updatedAt)}</span>
                </div>
              </button>
            ))}
          </div>
        </aside>

        <section className="panel detail-panel">
          {loadingResources || loadingDetail ? (
            <div className="detail-panel--empty">
              <p className="eyebrow">Detalle</p>
              <h2>Cargando recurso...</h2>
            </div>
          ) : !detail ? (
            <div className="detail-panel--empty">
              <p className="eyebrow">Detalle</p>
              <h2>Selecciona un recurso para revisar su checklist.</h2>
            </div>
          ) : (
            <>
              <header className="detail-header">
                <div>
                  <p className="eyebrow">{getResourceTypeLabel(detail.resource.type)}</p>
                  <h2>{detail.resource.title}</h2>
                  <p className="detail-header__path">
                    {detail.resource.coursePath ?? detail.resource.path ?? 'Sin ruta disponible'}
                  </p>
                </div>

                <div className="detail-header__badges">
                  <ReviewStateBadge state={detail.resource.reviewState} />
                  <InventoryStatusBadge status={detail.resource.status} />
                </div>
              </header>

              <div className="detail-meta">
                <div>
                  <span className="detail-meta__label">Origen</span>
                  <strong>{detail.resource.origin ?? 'No indicado'}</strong>
                </div>
                <div>
                  <span className="detail-meta__label">Sesión</span>
                  {reviewSession ? <SessionStatusBadge status={reviewSession.status} /> : <strong>Sin sesión</strong>}
                </div>
                <div>
                  <span className="detail-meta__label">Actualizado</span>
                  <strong>{formatDate(detail.resource.updatedAt)}</strong>
                </div>
              </div>

              {detail.resource.url ? (
                <a className="detail-link" href={detail.resource.url} target="_blank" rel="noreferrer">
                  Abrir recurso original
                </a>
              ) : null}

              {detail.resource.notes ? <p className="detail-notes">{detail.resource.notes}</p> : null}

              <div className="save-strip">
                <span className={`save-strip__status save-strip__status--${saveState}`}>{getSaveMessage(saveState)}</span>
                {saveState === 'error' ? (
                  <button type="button" className="secondary-button" onClick={handleRetrySave}>
                    Reintentar guardado
                  </button>
                ) : null}
              </div>

              {saveError ? <p className="error-text">{saveError}</p> : null}

              <div className="checklist-grid">
                {detail.checklist.items.map((item) => (
                  <article key={item.itemKey} className="checklist-card">
                    <div className="checklist-card__header">
                      <div>
                        <h3>{item.label}</h3>
                        {item.description ? <p>{item.description}</p> : null}
                      </div>
                      <span className={`value-chip value-chip--${item.value.toLowerCase()}`}>
                        {item.value === 'PASS' ? 'Cumple' : item.value === 'FAIL' ? 'No cumple' : 'Pendiente'}
                      </span>
                    </div>

                    <div className="segmented-control" role="group" aria-label={`Estado de ${item.label}`}>
                      {RESPONSE_OPTIONS.map((option) => (
                        <button
                          key={option.value}
                          type="button"
                          className={`segmented-control__button ${item.value === option.value ? 'segmented-control__button--active' : ''}`}
                          aria-pressed={item.value === option.value}
                          onClick={() => updateChecklistItem(item.itemKey, (current) => ({ ...current, value: option.value }))}
                        >
                          {option.label}
                        </button>
                      ))}
                    </div>

                    <label className="field-label" htmlFor={`comment-${item.itemKey}`}>
                      Comentario docente
                    </label>
                    <textarea
                      id={`comment-${item.itemKey}`}
                      className="comment-box"
                      rows={3}
                      value={item.comment ?? ''}
                      placeholder="Añade contexto, evidencia o el motivo del cambio"
                      onChange={(event) =>
                        updateChecklistItem(item.itemKey, (current) => ({ ...current, comment: event.target.value }))
                      }
                    />

                    <div className={`recommendation ${item.value === 'FAIL' ? 'recommendation--strong' : ''}`}>
                      <span>Recomendación para el informe</span>
                      <p>{item.recommendation ?? 'Sin recomendación registrada para este criterio.'}</p>
                    </div>
                  </article>
                ))}
              </div>
            </>
          )}
        </section>
      </div>
    </LayoutSimple>
  );
}
