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
  CourseStructure,
  CourseStructureOrganization,
  CourseStructureNode,
  ResourceDetailResponse,
  ResourceListItem,
  ReviewChecklistItem,
  ReviewChecklistValue,
} from '../lib/types';
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

const RESPONSE_OPTIONS: Array<{ label: string; value: ReviewChecklistValue }> = [
  { label: 'Cumple', value: 'PASS' },
  { label: 'No cumple', value: 'FAIL' },
  { label: 'Pendiente', value: 'PENDING' },
];

function getStructureNodeKey(node: CourseStructureNode | CourseStructureOrganization, prefix = 'node') {
  return `${prefix}:${node.nodeId}`;
}

function countVisibleResources(
  node: CourseStructureNode | CourseStructureOrganization,
  resourceIds: Set<string>,
): number {
  const ownResourceCount =
    'resourceId' in node && node.resourceId && resourceIds.has(node.resourceId) ? 1 : 0;
  return ownResourceCount + node.children.reduce((total, child) => total + countVisibleResources(child, resourceIds), 0);
}

function pruneCourseStructureNode(
  node: CourseStructureNode,
  resourceIds: Set<string>,
): CourseStructureNode | null {
  const children = node.children
    .map((child) => pruneCourseStructureNode(child, resourceIds))
    .filter((child): child is CourseStructureNode => child !== null);
  const hasOwnResource = node.resourceId ? resourceIds.has(node.resourceId) : false;

  if (!hasOwnResource && children.length === 0) {
    return null;
  }

  return {
    ...node,
    children,
  };
}

function pruneCourseStructure(
  structure: CourseStructure | null,
  resourceIds: Set<string>,
): CourseStructure | null {
  if (!structure) {
    return null;
  }

  const organizations = structure.organizations
    .map((organization) => {
      const children = organization.children
        .map((child) => pruneCourseStructureNode(child, resourceIds))
        .filter((child): child is CourseStructureNode => child !== null);

      if (children.length === 0) {
        return null;
      }

      return {
        ...organization,
        children,
      };
    })
    .filter((organization): organization is CourseStructureOrganization => organization !== null);

  const unplacedResourceIds = structure.unplacedResourceIds.filter((resourceId) => resourceIds.has(resourceId));

  if (organizations.length === 0 && unplacedResourceIds.length === 0) {
    return null;
  }

  return {
    ...structure,
    organizations,
    unplacedResourceIds,
  };
}

function findBranchKeysForFirstVisibleResource(
  node: CourseStructureNode | CourseStructureOrganization,
  resourceIds: Set<string>,
): string[] {
  if (countVisibleResources(node, resourceIds) === 0) {
    return [];
  }

  const branchKey = node.children.length > 0 ? [getStructureNodeKey(node)] : [];
  for (const child of node.children) {
    const childKeys = findBranchKeysForFirstVisibleResource(child, resourceIds);
    if (childKeys.length > 0) {
      return [...branchKey, ...childKeys];
    }
  }

  return branchKey;
}

function buildInitialExpandedSections(
  structure: CourseStructure | null,
  resources: ResourceListItem[],
): Record<string, boolean> {
  const visibleResourceIds = new Set(resources.map((resource) => resource.id));

  if (structure?.organizations.length) {
    for (const organization of structure.organizations) {
      if (countVisibleResources(organization, visibleResourceIds) === 0) {
        continue;
      }

      const keys = [
        getStructureNodeKey(organization, 'org'),
        ...findBranchKeysForFirstVisibleResource(organization, visibleResourceIds),
      ];
      return Object.fromEntries(keys.map((key) => [key, true]));
    }

    return { [getStructureNodeKey(structure.organizations[0], 'org')]: true };
  }

  return {};
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
  const [courseStructure, setCourseStructure] = useState<CourseStructure | null>(null);
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({});
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
  const [showOnlyBroken, setShowOnlyBroken] = useState(false);
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

    fetchResources(jobId, { onlyBroken: showOnlyBroken })
      .then((payload) => {
        if (cancelled) {
          return;
        }

        setResources(payload.resources);
        setCourseStructure(payload.structure);
        setExpandedSections((current) => {
          if (Object.values(current).some(Boolean)) {
            return current;
          }

          return buildInitialExpandedSections(payload.structure, payload.resources);
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
  }, [jobId, showOnlyBroken]);

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
        const refreshed = await fetchResources(jobId, { onlyBroken: showOnlyBroken });
        setResources(refreshed.resources);
        setCourseStructure(refreshed.structure);
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
  }, [detail, jobId, showOnlyBroken]);

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

  const resourceIndex = useMemo(
    () => new Map(resources.map((resource) => [resource.id, resource])),
    [resources],
  );

  const visibleResourceIds = useMemo(
    () => new Set(resources.map((resource) => resource.id)),
    [resources],
  );

  const visibleCourseStructure = useMemo(
    () => pruneCourseStructure(courseStructure, visibleResourceIds),
    [courseStructure, visibleResourceIds],
  );

  const unmappedResources = useMemo(
    () =>
      (visibleCourseStructure?.unplacedResourceIds ?? [])
        .map((resourceId) => resourceIndex.get(resourceId))
        .filter((resource): resource is ResourceListItem => resource !== undefined),
    [resourceIndex, visibleCourseStructure],
  );

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

  function renderResourceContent(resource: ResourceListItem, domScope: string) {
    const encodedScope = encodeURIComponent(domScope);
    const resourceButtonId = `resource-button-${encodedScope}`;
    const resourcePanelId = `resource-panel-${encodedScope}`;
    const isExpanded = expandedResourceId === resource.id;
    const visualState = getVisualReviewState(resource, resourceActivityMap[resource.id]);

    return (
      <>
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
                {getHealthLabel(resource) ? ` · ${getHealthLabel(resource)}` : ''}
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
                {resource.itemPath ||
                resource.modulePath ||
                resource.coursePath ||
                resource.sourceUrl ||
                resource.filePath ||
                resource.localPath ||
                resource.path ? (
                  <div className="space-y-2 rounded-2xl border border-line bg-[#f9faf7] p-4 text-sm text-subtle">
                    {resource.itemPath ? (
                      <p>
                        <span className="font-semibold text-ink">Ubicación docente:</span>{' '}
                        {resource.itemPath}
                      </p>
                    ) : null}
                    {resource.modulePath || resource.coursePath ? (
                      <p>
                        <span className="font-semibold text-ink">Módulo:</span>{' '}
                        {resource.modulePath ?? resource.coursePath}
                      </p>
                    ) : null}
                    {resource.sourceUrl ? (
                      <p>
                        <span className="font-semibold text-ink">URL de origen:</span>{' '}
                        <a
                          className="underline"
                          href={resource.sourceUrl}
                          rel="noreferrer"
                          target="_blank"
                        >
                          Abrir recurso
                        </a>
                      </p>
                    ) : null}
                    {resource.filePath || resource.localPath ? (
                      <p>
                        <span className="font-semibold text-ink">Archivo interno:</span>{' '}
                        {resource.filePath ?? resource.localPath}
                      </p>
                    ) : null}
                    {resource.urlStatus ? (
                      <p>
                        <span className="font-semibold text-ink">Comprobación URL:</span>{' '}
                        {resource.urlStatus}
                        {resource.checkedAt
                          ? ` · ${new Date(resource.checkedAt).toLocaleString('es-ES')}`
                          : ''}
                      </p>
                    ) : null}
                    {resource.finalUrl && resource.finalUrl !== resource.sourceUrl ? (
                      <p>
                        <span className="font-semibold text-ink">URL final:</span>{' '}
                        <a
                          className="underline"
                          href={resource.finalUrl}
                          rel="noreferrer"
                          target="_blank"
                        >
                          Abrir destino final
                        </a>
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
      </>
    );
  }

  function renderResourceRow(resource: ResourceListItem, domScope = resource.id) {
    return (
      <li className="px-4 py-2 sm:px-6" key={`${domScope}:${resource.id}`}>
        {renderResourceContent(resource, domScope)}
      </li>
    );
  }

  function renderStructureNode(node: CourseStructureNode): JSX.Element | null {
    const resource = node.resourceId ? resourceIndex.get(node.resourceId) ?? null : null;
    const resourceCount = countVisibleResources(node, visibleResourceIds);
    const nodeKey = getStructureNodeKey(node);

    if (resourceCount === 0) {
      return null;
    }

    if (node.children.length === 0 && resource) {
      return renderResourceRow(resource, nodeKey);
    }

    const buttonId = `course-node-button-${encodeURIComponent(nodeKey)}`;
    const panelId = `course-node-panel-${encodeURIComponent(nodeKey)}`;
    const isExpanded = expandedSections[nodeKey] ?? false;

    return (
      <li className="space-y-3" key={nodeKey}>
        <div className="rounded-2xl border border-line bg-white">
          <h3>
            <button
              aria-controls={panelId}
              aria-expanded={isExpanded}
              className="flex w-full items-center justify-between gap-4 px-4 py-4 text-left text-base font-semibold text-ink sm:px-5"
              id={buttonId}
              onClick={() =>
                setExpandedSections((current) => ({
                  ...current,
                  [nodeKey]: !current[nodeKey],
                }))
              }
              type="button"
            >
              <span className="min-w-0 truncate">{node.title}</span>
              <span className="text-sm font-medium text-subtle">{resourceCount}</span>
            </button>
          </h3>

          <div
            aria-labelledby={buttonId}
            className="border-t border-line px-3 py-3 sm:px-4"
            hidden={!isExpanded}
            id={panelId}
            role="region"
          >
            {resource ? (
              <ul className="divide-y divide-line overflow-hidden rounded-2xl border border-line">
                {renderResourceRow(resource, `${nodeKey}:resource`)}
              </ul>
            ) : null}

            {node.children.length > 0 ? (
              <div className={resource ? 'mt-3 border-t border-dashed border-line pt-3' : undefined}>
                <ul className="space-y-3 border-l border-line pl-4 sm:pl-5">
                  {node.children.map((child) => renderStructureNode(child))}
                </ul>
              </div>
            ) : null}
          </div>
        </div>
      </li>
    );
  }

  const showCourseTree = Boolean(
    (visibleCourseStructure?.organizations.length ?? 0) > 0 || unmappedResources.length > 0,
  );

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

      {!loadingResources && !screenError ? (
        <section className="card-panel mb-4 p-4 sm:p-5">
          <label className="flex cursor-pointer items-start gap-3 text-sm text-ink">
            <input
              checked={showOnlyBroken}
              className="mt-1 h-4 w-4 rounded border-line text-ink focus:ring-ink"
              onChange={(event) => setShowOnlyBroken(event.target.checked)}
              type="checkbox"
            />
            <span>
              <span className="block font-semibold">Mostrar solo enlaces rotos</span>
              <span className="block text-subtle">
                Filtra rápidamente recursos con 404, 5xx o timeout.
              </span>
            </span>
          </label>
        </section>
      ) : null}

      {!loadingResources && !screenError && resources.length === 0 ? (
        <section className="card-panel p-6 text-sm text-subtle">
          {showOnlyBroken ? 'No hay enlaces rotos en este curso.' : 'No hay recursos para revisar.'}
        </section>
      ) : null}

      {!loadingResources && !screenError && resources.length > 0 ? (
        <div className="space-y-4">
          {showCourseTree ? (
            <>
              {visibleCourseStructure?.organizations.map((organization) => {
                const organizationKey = getStructureNodeKey(organization, 'org');
                const organizationCount = countVisibleResources(organization, visibleResourceIds);
                const buttonId = `resource-organization-button-${encodeURIComponent(organizationKey)}`;
                const panelId = `resource-organization-panel-${encodeURIComponent(organizationKey)}`;
                const isExpanded = expandedSections[organizationKey] ?? false;

                return (
                  <section className="card-panel overflow-hidden" key={organizationKey}>
                    <h2>
                      <button
                        aria-controls={panelId}
                        aria-expanded={isExpanded}
                        className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left text-base font-semibold text-ink sm:px-6"
                        id={buttonId}
                        onClick={() =>
                          setExpandedSections((current) => ({
                            ...current,
                            [organizationKey]: !current[organizationKey],
                          }))
                        }
                        type="button"
                      >
                        <span>{organization.title}</span>
                        <span className="text-sm font-medium text-subtle">
                          {organizationCount}
                        </span>
                      </button>
                    </h2>

                    <div
                      aria-labelledby={buttonId}
                      className="border-t border-line px-4 py-4 sm:px-6"
                      hidden={!isExpanded}
                      id={panelId}
                      role="region"
                    >
                      <ul className="space-y-3">
                        {organization.children.map((child) => renderStructureNode(child))}
                      </ul>
                    </div>
                  </section>
                );
              })}

              {unmappedResources.length > 0 ? (
                <section className="card-panel overflow-hidden">
                  <div className="flex items-center justify-between gap-4 border-b border-line px-5 py-4 sm:px-6">
                    <h2 className="text-base font-semibold text-ink">
                      No ubicados en la estructura del curso
                    </h2>
                    <span className="text-sm font-medium text-subtle">
                      {unmappedResources.length}
                    </span>
                  </div>
                  <ul className="divide-y divide-line">
                    {unmappedResources.map((resource) => renderResourceRow(resource, `unmapped:${resource.id}`))}
                  </ul>
                </section>
              ) : null}
            </>
          ) : (
            <section className="card-panel p-6 text-sm text-subtle">
              {showOnlyBroken
                ? 'No hay enlaces rotos dentro de la estructura visible del curso.'
                : 'No se ha podido reconstruir la estructura visible del curso.'}
            </section>
          )}

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
