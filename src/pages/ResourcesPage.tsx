import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';
import {
  fetchResourceDetail,
  fetchResources,
  generateReport,
  saveChecklist,
} from '../lib/api';
import type {
  AppMode,
  ResourceDetailResponse,
  ResourceListItem,
  ReviewChecklistItem,
  ReviewChecklistValue,
} from '../lib/types';
import { sortResourcesByPriority } from '../lib/types';
import {
  classNames,
  getModeSearch,
  isAppMode,
  loadRememberedAppMode,
  loadRememberedCourseName,
  rememberAppMode,
} from '../lib/utils';

type SaveState = 'idle' | 'pending' | 'saving' | 'saved' | 'error';
type VisualReviewState = 'SIN_REVISAR' | 'EN_REVISION' | 'OK' | 'REQUIERE_CAMBIOS';
const DEFAULT_MODULE_LABEL = 'Contenido sin módulo';

const RESPONSE_OPTIONS: Array<{ label: string; value: ReviewChecklistValue }> = [
  { label: 'Cumple', value: 'PASS' },
  { label: 'No cumple', value: 'FAIL' },
  { label: 'Pendiente', value: 'PENDING' },
];

function getGroupKey(resource: ResourceListItem): string {
  return resource.coursePath?.trim() || DEFAULT_MODULE_LABEL;
}

function hasChecklistActivity(items: ReviewChecklistItem[]) {
  return items.some((item) => item.value !== 'PENDING' || Boolean(item.comment?.trim()));
}

function parseCommentFields(comment: string | null) {
  const rawValue = comment?.trim() ?? '';
  if (!rawValue) {
    return { commentText: '', reportRecommendation: '' };
  }

  const recommendationMarker = 'Recomendación para el informe:';
  const recommendationIndex = rawValue.indexOf(recommendationMarker);

  if (recommendationIndex === -1) {
    return {
      commentText: rawValue.replace(/^Comentario:\s*/i, '').trim(),
      reportRecommendation: '',
    };
  }

  const commentText = rawValue
    .slice(0, recommendationIndex)
    .replace(/^Comentario:\s*/i, '')
    .trim();

  const reportRecommendation = rawValue
    .slice(recommendationIndex + recommendationMarker.length)
    .trim();

  return { commentText, reportRecommendation };
}

function serializeCommentFields(commentText: string, reportRecommendation: string) {
  const nextComment = commentText.trim();
  const nextRecommendation = reportRecommendation.trim();

  if (nextComment && nextRecommendation) {
    return `Comentario:\n${nextComment}\n\nRecomendación para el informe:\n${nextRecommendation}`;
  }

  if (nextRecommendation) {
    return `Recomendación para el informe:\n${nextRecommendation}`;
  }

  return nextComment;
}

function getVisualReviewState(
  resource: ResourceListItem,
  hasActivity: boolean | undefined,
): VisualReviewState {
  if (resource.reviewState === 'OK') {
    return 'OK';
  }

  if (resource.reviewState === 'NEEDS_FIX') {
    return 'REQUIERE_CAMBIOS';
  }

  return hasActivity ? 'EN_REVISION' : 'SIN_REVISAR';
}

function getReviewStateLabel(state: VisualReviewState) {
  switch (state) {
    case 'OK':
      return 'OK';
    case 'REQUIERE_CAMBIOS':
      return 'Requiere cambios';
    case 'EN_REVISION':
      return 'En revisión';
    default:
      return 'Sin revisar';
  }
}

function getReviewStateClassName(state: VisualReviewState) {
  switch (state) {
    case 'OK':
      return 'border-emerald-200 bg-emerald-50 text-[#166534]';
    case 'REQUIERE_CAMBIOS':
      return 'border-rose-200 bg-rose-50 text-danger';
    case 'EN_REVISION':
      return 'border-amber-200 bg-amber-50 text-[#8a5a00]';
    default:
      return 'border-slate-200 bg-slate-50 text-slate-700';
  }
}

function getHealthLabel(resource: ResourceListItem) {
  if (resource.status === 'ERROR') {
    return 'Enlace roto';
  }
  if (resource.status === 'WARN') {
    return 'Revisar enlace';
  }
  return null;
}

function getFooterMessage(
  saveState: SaveState,
  saveError: string | null,
  generationError: string | null,
  isGenerating: boolean,
) {
  if (generationError) {
    return generationError;
  }

  if (isGenerating) {
    return 'Generando informe…';
  }

  if (saveState === 'saving') {
    return 'Guardando cambios…';
  }

  if (saveState === 'saved') {
    return 'Cambios guardados.';
  }

  if (saveState === 'error') {
    return saveError ?? 'No se pudieron guardar los cambios.';
  }

  if (saveState === 'pending') {
    return 'Cambios pendientes. Se guardarán automáticamente.';
  }

  return 'Puedes generar el informe en cualquier momento.';
}

export function ResourcesPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [resources, setResources] = useState<ResourceListItem[]>([]);
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});
  const [expandedResourceId, setExpandedResourceId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ResourceDetailResponse | null>(null);
  const [loadingResources, setLoadingResources] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [screenError, setScreenError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [saveError, setSaveError] = useState<string | null>(null);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState('');
  const [isDirty, setIsDirty] = useState(false);
  const [draftVersion, setDraftVersion] = useState(0);
  const [isGenerating, setIsGenerating] = useState(false);
  const [resourceActivityMap, setResourceActivityMap] = useState<Record<string, boolean>>({});
  const draftVersionRef = useRef(0);
  const saveQueueRef = useRef<Promise<boolean>>(Promise.resolve(true));
  const modeParam = searchParams.get('mode');
  const appMode: AppMode = isAppMode(modeParam) ? modeParam : loadRememberedAppMode() ?? 'offline';

  useEffect(() => {
    rememberAppMode(appMode);
  }, [appMode]);

  useEffect(() => {
    if (!jobId) {
      setScreenError('Falta el identificador del curso.');
      setLoadingResources(false);
      return;
    }

    let cancelled = false;
    setLoadingResources(true);
    setScreenError(null);

    fetchResources(jobId)
      .then((payload) => {
        if (cancelled) {
          return;
        }

        const orderedResources = sortResourcesByPriority(payload.resources);
        setResources(orderedResources);
        setExpandedGroups((current) => {
          if (Object.values(current).some(Boolean)) {
            return current;
          }

          const firstOpenGroup = orderedResources[0] ? getGroupKey(orderedResources[0]) : null;

          if (!firstOpenGroup) {
            return current;
          }

          return { [firstOpenGroup]: true };
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
    if (!jobId || !expandedResourceId) {
      if (!expandedResourceId) {
        setDetail(null);
        setDetailError(null);
        setLoadingDetail(false);
      }

      return;
    }

    if (detail?.resource.id === expandedResourceId) {
      return;
    }

    let cancelled = false;
    setLoadingDetail(true);
    setDetailError(null);

    fetchResourceDetail(jobId, expandedResourceId)
      .then((payload) => {
        if (cancelled) {
          return;
        }

        setDetail(payload);
        setResourceActivityMap((current) => ({
          ...current,
          [payload.resource.id]: hasChecklistActivity(payload.checklist.items),
        }));
        setSaveState('idle');
        setSaveError(null);
        setIsDirty(false);
        draftVersionRef.current = 0;
        setDraftVersion(0);
      })
      .catch((error: Error) => {
        if (!cancelled) {
          setDetailError(error.message);
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
  }, [detail?.resource.id, expandedResourceId, jobId]);

  const persistDraft = useCallback(async (
    versionAtSave: number,
    snapshot = detail,
  ): Promise<boolean> => {
    if (!jobId || !snapshot) {
      return true;
    }

    const hasActivity = hasChecklistActivity(snapshot.checklist.items);
    const payload = {
      responses: snapshot.checklist.items.map((item) => ({
        itemKey: item.itemKey,
        value: item.value,
        ...(item.comment?.trim() ? { comment: item.comment.trim() } : {}),
      })),
    };

    const saveTask = saveQueueRef.current.then(async () => {
      setSaveState('saving');
      setSaveError(null);

      try {
        const result = await saveChecklist(jobId, snapshot.resource.id, payload);
        const refreshed = await fetchResources(jobId);
        const orderedResources = sortResourcesByPriority(refreshed.resources);

        setResources(orderedResources);
        setResourceActivityMap((current) => ({
          ...current,
          [snapshot.resource.id]: hasActivity,
        }));
        setDetail((current) => {
          if (!current || current.resource.id !== result.resourceId) {
            return current;
          }

          return {
            ...current,
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
          setAnnouncement('Cambios guardados.');
        } else {
          setSaveState('pending');
        }

        return true;
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : 'No se pudieron guardar los cambios.';

        setSaveState('error');
        setSaveError(message);
        setAnnouncement('No se pudieron guardar los cambios.');
        return false;
      }
    });

    saveQueueRef.current = saveTask.catch(() => false);
    return saveTask;
  }, [detail, jobId]);

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
  }, [detail, draftVersion, isDirty, persistDraft]);

  const groupedResources = useMemo(() => {
    const groups = new Map<string, ResourceListItem[]>();

    resources.forEach((resource) => {
      const groupKey = getGroupKey(resource);
      const items = groups.get(groupKey);
      if (items) {
        items.push(resource);
        return;
      }

      groups.set(groupKey, [resource]);
    });

    return Array.from(groups.entries()).map(([groupKey, items]) => ({
      groupKey,
      groupResources: items,
    }));
  }, [resources]);

  function updateChecklistItem(
    itemKey: string,
    updater: (item: ReviewChecklistItem) => ReviewChecklistItem,
  ) {
    setDetail((current) => {
      if (!current) {
        return current;
      }

      return {
        ...current,
        checklist: {
          ...current.checklist,
          items: current.checklist.items.map((item) =>
            item.itemKey === itemKey ? updater(item) : item,
          ),
        },
      };
    });

    setSaveState('pending');
    setSaveError(null);
    setGenerationError(null);
    setIsDirty(true);
    draftVersionRef.current += 1;
    setDraftVersion(draftVersionRef.current);
  }

  function handleResponseChange(itemKey: string, value: ReviewChecklistValue) {
    updateChecklistItem(itemKey, (item) => ({
      ...item,
      value,
    }));
  }

  function handleTextChange(
    itemKey: string,
    commentText: string,
    reportRecommendation: string,
  ) {
    updateChecklistItem(itemKey, (item) => ({
      ...item,
      comment: serializeCommentFields(commentText, reportRecommendation) || null,
    }));
  }

  async function handleToggleResource(resourceId: string) {
    if (detail && isDirty) {
      await persistDraft(draftVersionRef.current, detail);
    } else {
      await saveQueueRef.current;
    }

    setDetailError(null);
    setGenerationError(null);
    setExpandedResourceId((current) => (current === resourceId ? null : resourceId));
  }

  async function handleGenerateReport() {
    if (!jobId) {
      return;
    }

    setGenerationError(null);
    setAnnouncement('');

    const saveSucceeded = detail && isDirty
      ? await persistDraft(draftVersionRef.current, detail)
      : await saveQueueRef.current;

    if (!saveSucceeded) {
      setGenerationError('No se pudo guardar la revisión antes de generar el informe.');
      return;
    }

    try {
      setIsGenerating(true);
      await generateReport(jobId);
      navigate(`/report/${jobId}${getModeSearch(appMode)}`, {
        replace: true,
        state: {
          announcement: 'Informe generado.',
          courseName: loadRememberedCourseName(jobId),
        },
      });
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : 'No se pudo generar el informe.';
      setGenerationError(message);
      setAnnouncement('No se pudo generar el informe.');
    } finally {
      setIsGenerating(false);
    }
  }

  return (
    <LayoutSimple
      backLabel="Volver"
      backTo={`/${appMode}${getModeSearch(appMode)}`}
      description="Revisa recursos y marca la checklist; el informe se genera a partir de esta revisión manual."
      title="Recursos"
    >
      <p aria-live="polite" className="sr-only">
        {announcement}
      </p>

      {screenError ? (
        <div
          aria-live="assertive"
          className="mb-6 rounded-2xl border border-rose-200 bg-rose-50 p-5 text-danger"
          role="alert"
        >
          {screenError}
        </div>
      ) : null}

      {loadingResources ? (
        <section className="card-panel p-6 text-sm text-subtle">
          Cargando recursos…
        </section>
      ) : null}

      {!loadingResources && !screenError && resources.length === 0 ? (
        <section className="card-panel p-6 text-sm text-subtle">
          No hay recursos para revisar.
        </section>
      ) : null}

      {!loadingResources && !screenError && resources.length > 0 ? (
        <div className="space-y-4">
          {groupedResources.map(({ groupKey, groupResources }) => {
            const groupDomKey = encodeURIComponent(groupKey);
            const groupButtonId = `resource-group-button-${groupDomKey}`;
            const groupPanelId = `resource-group-panel-${groupDomKey}`;
            const isGroupExpanded = expandedGroups[groupKey] ?? false;

            return (
              <section className="card-panel overflow-hidden" key={groupKey}>
                <h2>
                  <button
                    aria-controls={groupPanelId}
                    aria-expanded={isGroupExpanded}
                    className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left text-base font-semibold text-ink sm:px-6"
                    id={groupButtonId}
                    onClick={() =>
                      setExpandedGroups((current) => ({
                        ...current,
                        [groupKey]: !current[groupKey],
                      }))
                    }
                    type="button"
                  >
                    <span>{groupKey}</span>
                    <span className="text-sm font-medium text-subtle">
                      {groupResources.length}
                    </span>
                  </button>
                </h2>

                <div
                  aria-labelledby={groupButtonId}
                  className="border-t border-line"
                  hidden={!isGroupExpanded}
                  id={groupPanelId}
                  role="region"
                >
                  <ul className="divide-y divide-line">
                    {groupResources.map((resource) => {
                      const resourceButtonId = `resource-button-${resource.id}`;
                      const resourcePanelId = `resource-panel-${resource.id}`;
                      const isExpanded = expandedResourceId === resource.id;
                      const visualState = getVisualReviewState(
                        resource,
                        resourceActivityMap[resource.id],
                      );

                      return (
                        <li className="px-4 py-2 sm:px-6" key={resource.id}>
                          <h3>
                            <button
                              aria-controls={resourcePanelId}
                              aria-expanded={isExpanded}
                              className="flex w-full items-center justify-between gap-4 rounded-2xl px-3 py-3 text-left transition hover:bg-[#f6f7f2]"
                              id={resourceButtonId}
                              onClick={() => {
                                void handleToggleResource(resource.id);
                              }}
                              type="button"
                            >
                              <span className="min-w-0 text-base font-semibold text-ink">
                                <span className="block truncate">{resource.title}</span>
                                <span className="mt-1 block text-sm font-normal text-subtle">
                                  {resource.type}
                                  {getHealthLabel(resource)
                                    ? ` · ${getHealthLabel(resource)}`
                                    : ''}
                                </span>
                              </span>
                              <span
                                className={classNames(
                                  'inline-flex shrink-0 rounded-full border px-3 py-1 text-sm font-semibold',
                                  getReviewStateClassName(visualState),
                                )}
                              >
                                {getReviewStateLabel(visualState)}
                              </span>
                            </button>
                          </h3>

                          {isExpanded ? (
                            <div
                              aria-labelledby={resourceButtonId}
                              className="pb-4 pt-2"
                              id={resourcePanelId}
                              role="region"
                            >
                              {loadingDetail ? (
                                <div className="rounded-2xl border border-line bg-[#f6f7f2] p-4 text-sm text-subtle">
                                  Cargando checklist…
                                </div>
                              ) : null}

                              {detailError ? (
                                <div
                                  aria-live="assertive"
                                  className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-danger"
                                  role="alert"
                                >
                                  {detailError}
                                </div>
                              ) : null}

                              {!loadingDetail &&
                              !detailError &&
                              detail &&
                              detail.resource.id === resource.id ? (
                                <div className="space-y-5">
                                  {resource.coursePath || resource.url || resource.localPath || resource.path ? (
                                    <div className="space-y-2 rounded-2xl border border-line bg-[#f9faf7] p-4 text-sm text-subtle">
                                      {resource.coursePath ? (
                                        <p>
                                          <span className="font-semibold text-ink">Ruta:</span>{' '}
                                          {resource.coursePath}
                                        </p>
                                      ) : null}
                                      {resource.url ? (
                                        <p>
                                          <span className="font-semibold text-ink">URL:</span>{' '}
                                          <a
                                            className="underline"
                                            href={resource.url}
                                            rel="noreferrer"
                                            target="_blank"
                                          >
                                            Abrir recurso
                                          </a>
                                        </p>
                                      ) : null}
                                      {resource.localPath ? (
                                        <p>
                                          <span className="font-semibold text-ink">Archivo:</span>{' '}
                                          {resource.localPath}
                                        </p>
                                      ) : null}
                                      {getHealthLabel(resource) ? (
                                        <p>
                                          <span className="font-semibold text-ink">Estado técnico:</span>{' '}
                                          {getHealthLabel(resource)}
                                        </p>
                                      ) : null}
                                      {resource.notes ? (
                                        <p>
                                          <span className="font-semibold text-ink">Detalle:</span>{' '}
                                          {resource.notes}
                                        </p>
                                      ) : null}
                                    </div>
                                  ) : null}

                                  <ul className="space-y-4">
                                    {detail.checklist.items.map((item) => {
                                      const commentFields = parseCommentFields(item.comment);
                                      const radiosName = `criterion-${resource.id}-${item.itemKey}`;
                                      const commentId = `criterion-comment-${resource.id}-${item.itemKey}`;
                                      const recommendationId = `criterion-recommendation-${resource.id}-${item.itemKey}`;

                                      return (
                                        <li
                                          className="rounded-2xl border border-line p-4"
                                          key={item.itemKey}
                                        >
                                          <div>
                                            <p className="text-base font-semibold text-ink">
                                              {item.label}
                                            </p>
                                            {item.description ? (
                                              <p className="mt-1 text-sm text-subtle">
                                                {item.description}
                                              </p>
                                            ) : null}
                                          </div>

                                          <fieldset className="mt-4">
                                            <legend className="sr-only">
                                              Estado del criterio {item.label}
                                            </legend>
                                            <div className="grid gap-2 sm:grid-cols-3">
                                              {RESPONSE_OPTIONS.map((option) => (
                                                <label
                                                  className={classNames(
                                                    'flex cursor-pointer items-center justify-center rounded-xl border px-3 py-3 text-sm font-semibold transition',
                                                    item.value === option.value
                                                      ? 'border-ink bg-[#edf2ea] text-ink'
                                                      : 'border-line bg-white text-subtle hover:bg-[#f6f7f2]',
                                                  )}
                                                  key={option.value}
                                                >
                                                  <input
                                                    checked={item.value === option.value}
                                                    className="sr-only"
                                                    name={radiosName}
                                                    onChange={() =>
                                                      handleResponseChange(
                                                        item.itemKey,
                                                        option.value,
                                                      )
                                                    }
                                                    type="radio"
                                                  />
                                                  <span>{option.label}</span>
                                                </label>
                                              ))}
                                            </div>
                                          </fieldset>

                                          <div className="mt-4 grid gap-4 lg:grid-cols-2">
                                            <div>
                                              <label
                                                className="block text-sm font-semibold text-ink"
                                                htmlFor={commentId}
                                              >
                                                Comentario
                                              </label>
                                              <textarea
                                                className="field-textarea mt-2 min-h-28"
                                                id={commentId}
                                                onChange={(event) =>
                                                  handleTextChange(
                                                    item.itemKey,
                                                    event.target.value,
                                                    commentFields.reportRecommendation,
                                                  )
                                                }
                                                rows={4}
                                                value={commentFields.commentText}
                                              />
                                            </div>

                                            <div>
                                              <label
                                                className="block text-sm font-semibold text-ink"
                                                htmlFor={recommendationId}
                                              >
                                                Recomendación para el informe
                                              </label>
                                              <textarea
                                                className="field-textarea mt-2 min-h-28"
                                                id={recommendationId}
                                                onChange={(event) =>
                                                  handleTextChange(
                                                    item.itemKey,
                                                    commentFields.commentText,
                                                    event.target.value,
                                                  )
                                                }
                                                rows={4}
                                                value={commentFields.reportRecommendation}
                                              />
                                            </div>
                                          </div>
                                        </li>
                                      );
                                    })}
                                  </ul>
                                </div>
                              ) : null}
                            </div>
                          ) : null}
                        </li>
                      );
                    })}
                  </ul>
                </div>
              </section>
            );
          })}

          <div className="sticky bottom-4 z-10 pt-2">
            <section className="card-panel border-[#dce4d8] bg-[rgba(255,255,255,0.96)] p-4 backdrop-blur">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-sm font-semibold text-ink">Generar informe</p>
                  <p className="mt-1 text-sm text-subtle">
                    {getFooterMessage(
                      saveState,
                      saveError,
                      generationError,
                      isGenerating,
                    )}
                  </p>
                </div>

                <button
                  className="button-primary w-full sm:w-auto"
                  disabled={isGenerating}
                  onClick={() => {
                    void handleGenerateReport();
                  }}
                  type="button"
                >
                  {isGenerating ? 'Generando informe…' : 'Generar informe'}
                </button>
              </div>
            </section>
          </div>
        </div>
      ) : null}
    </LayoutSimple>
  );
}
