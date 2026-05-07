import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';
import { api, fetchAccessibility, fetchResources } from '../lib/api';
import type {
  AccessibilityCheckStatus,
  AccessibilityResource,
  AccessibilityResponse,
  AppMode,
  CourseStructure,
  CourseStructureNode,
  ResourceListItem,
} from '../lib/types';
import {
  classNames,
  getModeSearch,
  isAppMode,
  loadRememberedAppMode,
  loadRememberedCourseName,
  rememberAppMode,
} from '../lib/utils';

interface ResourceGroup {
  id: string;
  section: string;
  isGlobalUnplaced: boolean;
  resources: ResourceListItem[];
}

const GLOBAL_UNPLACED_SECTION_LABEL =
  'Recursos globales o no ubicados en la estructura del curso';

function normalizeComparableText(value: string | null | undefined) {
  return (
    value
      ?.trim()
      .toLocaleLowerCase('es-ES')
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '') ?? ''
  );
}

function isGlobalUnplacedType(value: string | null | undefined) {
  const normalizedValue = normalizeComparableText(value);
  return (
    normalizedValue === 'global_unplaced' ||
    normalizedValue === 'global-unplaced' ||
    normalizedValue === 'unplaced'
  );
}

function isGlobalUnplacedName(value: string | null | undefined) {
  const normalizedValue = normalizeComparableText(value);
  return (
    !normalizedValue ||
    normalizedValue === 'global_unplaced' ||
    normalizedValue.includes('sin seccion') ||
    normalizedValue.includes('no ubicado') ||
    normalizedValue.includes('unplaced')
  );
}

function normalizeSectionName(value: string | null | undefined) {
  return isGlobalUnplacedName(value)
    ? GLOBAL_UNPLACED_SECTION_LABEL
    : (value?.trim() ?? GLOBAL_UNPLACED_SECTION_LABEL);
}

function getSectionLabel(resource: ResourceListItem) {
  const sectionName =
    resource.sectionTitle ||
    resource.moduleTitle ||
    resource.modulePath ||
    resource.coursePath;

  if (
    isGlobalUnplacedType(resource.sectionType) ||
    isGlobalUnplacedName(sectionName)
  ) {
    return GLOBAL_UNPLACED_SECTION_LABEL;
  }

  return normalizeSectionName(sectionName);
}

function uniqueResources(resources: ResourceListItem[]) {
  const seenResourceIds = new Set<string>();
  return resources.filter((resource) => {
    if (seenResourceIds.has(resource.id)) {
      return false;
    }

    seenResourceIds.add(resource.id);
    return true;
  });
}

function collectNodeResources(
  node: CourseStructureNode,
  resourcesById: Map<string, ResourceListItem>,
): ResourceListItem[] {
  const collected: ResourceListItem[] = [];

  if (node.resourceId) {
    const resource = resourcesById.get(node.resourceId);
    if (resource) {
      collected.push(resource);
    }
  }

  node.children.forEach((childNode) => {
    collected.push(...collectNodeResources(childNode, resourcesById));
  });

  return uniqueResources(collected);
}

function createGroup(
  id: string,
  title: string | null | undefined,
  resources: ResourceListItem[],
): ResourceGroup {
  const section = normalizeSectionName(title);

  return {
    id,
    section,
    isGlobalUnplaced: section === GLOBAL_UNPLACED_SECTION_LABEL,
    resources: uniqueResources(resources),
  };
}

function buildGroupsByPath(resources: ResourceListItem[]) {
  const groups = new Map<string, ResourceListItem[]>();

  resources.forEach((resource) => {
    const section = getSectionLabel(resource);
    groups.set(section, [...(groups.get(section) ?? []), resource]);
  });

  return Array.from(groups.entries()).map(([section, sectionResources]) =>
    createGroup(section, section, sectionResources),
  );
}

function sortGlobalGroupLast(groups: ResourceGroup[]) {
  return [...groups].sort((left, right) => {
    if (left.isGlobalUnplaced === right.isGlobalUnplaced) {
      return 0;
    }

    return left.isGlobalUnplaced ? 1 : -1;
  });
}

function buildGroupsFromStructure(
  structure: CourseStructure,
  resources: ResourceListItem[],
) {
  const resourcesById = new Map(
    resources.map((resource) => [resource.id, resource]),
  );
  const groupedResourceIds = new Set<string>();
  const groups: ResourceGroup[] = [];

  structure.organizations.forEach((organization) => {
    const organizationDirectResources: ResourceListItem[] = [];

    organization.children.forEach((node) => {
      if (node.resourceId && node.children.length === 0) {
        const resource = resourcesById.get(node.resourceId);
        if (resource) {
          organizationDirectResources.push(resource);
          groupedResourceIds.add(resource.id);
        }
        return;
      }

      const nodeResources = collectNodeResources(node, resourcesById);
      if (nodeResources.length === 0) {
        return;
      }

      nodeResources.forEach((resource) => groupedResourceIds.add(resource.id));
      groups.push(createGroup(node.nodeId, node.title, nodeResources));
    });

    if (organizationDirectResources.length > 0) {
      groups.push(
        createGroup(
          `${organization.nodeId}-direct`,
          organization.title,
          organizationDirectResources,
        ),
      );
    }
  });

  const unplacedResources = structure.unplacedResourceIds
    .map((resourceId) => resourcesById.get(resourceId))
    .filter((resource): resource is ResourceListItem => {
      if (!resource) {
        return false;
      }

      return !groupedResourceIds.has(resource.id);
    });

  unplacedResources.forEach((resource) => groupedResourceIds.add(resource.id));

  if (unplacedResources.length > 0) {
    groups.push(
      createGroup(
        'unplaced-resources',
        GLOBAL_UNPLACED_SECTION_LABEL,
        unplacedResources,
      ),
    );
  }

  const remainingResources = resources.filter(
    (resource) => !groupedResourceIds.has(resource.id),
  );

  return sortGlobalGroupLast([
    ...groups,
    ...buildGroupsByPath(remainingResources),
  ]);
}

function toPanelId(prefix: string, id: string) {
  const normalizedId =
    id.replace(/[^a-zA-Z0-9_-]+/g, '-').replace(/^-|-$/g, '') || 'panel';
  return `${prefix}-${normalizedId.toLowerCase()}`;
}

function getCheckScore(status: AccessibilityCheckStatus) {
  if (status === 'PASS' || status === 'NO_APLICA') {
    return 100;
  }

  if (status === 'WARNING') {
    return 70;
  }

  if (status === 'FAIL') {
    return 25;
  }

  return 0;
}

function getResourceScore(
  accessibilityResult: AccessibilityResource | undefined,
) {
  if (!accessibilityResult?.checks.length) {
    return null;
  }

  const total = accessibilityResult.checks.reduce(
    (sum, check) => sum + getCheckScore(check.status),
    0,
  );

  return Math.round(total / accessibilityResult.checks.length);
}

function averageScores(scores: Array<number | null>) {
  const scoredValues = scores.filter(
    (score): score is number => score !== null,
  );

  if (scoredValues.length === 0) {
    return null;
  }

  return Math.round(
    scoredValues.reduce((total, score) => total + score, 0) /
      scoredValues.length,
  );
}

function getScoreText(score: number | null) {
  return score === null ? 'Sin score' : `${score}/100`;
}

function getScoreTextClass(score: number | null) {
  if (score === null) {
    return 'text-subtle';
  }

  if (score >= 80) {
    return 'score-green';
  }

  if (score >= 60) {
    return 'score-yellow';
  }

  return 'score-red';
}

function getScoreBadgeClasses(score: number | null) {
  if (score === null) {
    return 'border-slate-200 bg-slate-50 text-slate-700';
  }

  if (score >= 80) {
    return 'border-emerald-200 bg-emerald-50 text-[#166534]';
  }

  if (score >= 60) {
    return 'border-amber-200 bg-amber-50 text-[#8a5a00]';
  }

  return 'border-rose-200 bg-rose-50 text-danger';
}

function ScoreBadge({
  className,
  score,
}: {
  className?: string;
  score: number | null;
}) {
  return (
    <span
      className={classNames(
        'inline-flex min-w-24 justify-center rounded-full border px-3 py-1 text-sm font-semibold',
        getScoreBadgeClasses(score),
        className,
      )}
    >
      {getScoreText(score)}
    </span>
  );
}

function ResourceScoreRow({
  accessibilityResult,
  resource,
}: {
  accessibilityResult: AccessibilityResource | undefined;
  resource: ResourceListItem;
}) {
  const score = getResourceScore(accessibilityResult);

  return (
    <li className="rounded-2xl border border-line bg-white px-4 py-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h4 className="break-words text-base font-semibold leading-6 text-ink">
          {resource.title}
        </h4>
        <ScoreBadge className="self-start sm:self-center" score={score} />
      </div>
    </li>
  );
}

export function ResourcesPage() {
  const navigate = useNavigate();
  const { jobId } = useParams<{ jobId: string }>();
  const [searchParams] = useSearchParams();
  const [resources, setResources] = useState<ResourceListItem[]>([]);
  const [structure, setStructure] = useState<CourseStructure | null>(null);
  const [accessibility, setAccessibility] =
    useState<AccessibilityResponse | null>(null);
  const [expandedPanels, setExpandedPanels] = useState<Record<string, boolean>>(
    {},
  );
  const [isLoading, setIsLoading] = useState(true);
  const [isRetrying, setIsRetrying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [accessibilityError, setAccessibilityError] = useState<string | null>(
    null,
  );
  const modeParam = searchParams.get('mode');
  const appMode: AppMode = isAppMode(modeParam)
    ? modeParam
    : (loadRememberedAppMode() ?? 'offline');

  useEffect(() => {
    rememberAppMode(appMode);
  }, [appMode]);

  useEffect(() => {
    if (!jobId) {
      setError('Falta el identificador del análisis.');
      setIsLoading(false);
      return;
    }

    const resolvedJobId = jobId;
    let cancelled = false;

    async function loadResources() {
      try {
        setIsLoading(true);
        setError(null);
        setAccessibilityError(null);
        const payload = await fetchResources(resolvedJobId);
        if (cancelled) {
          return;
        }

        setResources(payload.resources);
        setStructure(payload.structure);

        try {
          const accessibilityPayload = await fetchAccessibility(resolvedJobId);
          if (!cancelled) {
            setAccessibility(accessibilityPayload);
          }
        } catch (caughtAccessibilityError) {
          if (!cancelled) {
            setAccessibility(null);
            setAccessibilityError(
              caughtAccessibilityError instanceof Error
                ? caughtAccessibilityError.message
                : 'No hemos podido cargar la puntuación automática de accesibilidad.',
            );
          }
        }
      } catch (caughtError) {
        if (!cancelled) {
          setError(
            caughtError instanceof Error
              ? caughtError.message
              : 'No hemos podido cargar los recursos.',
          );
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void loadResources();

    return () => {
      cancelled = true;
    };
  }, [jobId]);

  const accessibilityByResourceId = useMemo(
    () =>
      new Map(
        (accessibility?.resources ?? []).map((resource) => [
          resource.resourceId,
          resource,
        ]),
      ),
    [accessibility],
  );
  const groups = useMemo(() => {
    if (structure) {
      return buildGroupsFromStructure(structure, resources);
    }

    return sortGlobalGroupLast(buildGroupsByPath(resources));
  }, [resources, structure]);
  const resourceScores = useMemo(
    () =>
      resources.map((resource) =>
        getResourceScore(accessibilityByResourceId.get(resource.id)),
      ),
    [accessibilityByResourceId, resources],
  );
  const globalScore = useMemo(
    () => averageScores(resourceScores),
    [resourceScores],
  );
  const rememberedCourseName = jobId ? loadRememberedCourseName(jobId) : null;
  const courseTitle =
    rememberedCourseName?.trim() ||
    structure?.title?.trim() ||
    (jobId ? `Curso ${jobId}` : 'Curso');

  const togglePanel = (panelId: string) => {
    setExpandedPanels((current) => ({
      ...current,
      [panelId]: !current[panelId],
    }));
  };

  const handleRetryAnalysis = async () => {
    if (!jobId) {
      return;
    }

    if (appMode === 'online') {
      navigate(`/online${getModeSearch('online')}`);
      return;
    }

    try {
      setIsRetrying(true);
      setError(null);
      await api.retryJob(jobId);
      navigate(`/analyzing/${jobId}${getModeSearch('offline')}`, {
        replace: true,
      });
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : 'No hemos podido relanzar el análisis.',
      );
      setIsRetrying(false);
    }
  };

  return (
    <LayoutSimple
      backLabel="Volver"
      backTo={`/${appMode}${getModeSearch(appMode)}`}
      showTokenButton={false}
      title={courseTitle}
      useMainLandmark={false}
    >
      {error ? (
        <div
          aria-live="assertive"
          className="mb-6 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-danger"
          role="alert"
        >
          {error}
        </div>
      ) : null}

      {isLoading ? (
        <section className="card-panel p-6 text-sm text-subtle">
          Cargando resultados del análisis...
        </section>
      ) : (
        <div className="space-y-7">
          <section aria-live="polite" className="border-b border-line pb-6">
            <h2 className="sr-only">Score total</h2>
            <p className="flex flex-col gap-3 text-xl font-semibold tracking-[-0.03em] text-ink sm:flex-row sm:items-center">
              <span>Score total</span>
              <span
                className={classNames(
                  'text-4xl font-semibold tracking-[-0.05em]',
                  getScoreTextClass(globalScore),
                )}
              >
                {getScoreText(globalScore)}
              </span>
            </p>
            {accessibilityError ? (
              <p className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-[#8a5a00]">
                No se pudo cargar la puntuación automática de accesibilidad:{' '}
                {accessibilityError}
              </p>
            ) : null}
          </section>

          <section className="space-y-4">
            <h2 className="text-xl font-semibold tracking-[-0.03em] text-ink">
              Recursos
            </h2>

            {groups.length === 0 ? (
              <div className="card-panel p-6 text-sm text-subtle">
                No hay recursos para mostrar.
              </div>
            ) : (
              <div className="space-y-3">
                {groups.map((group) => {
                  const panelId = toPanelId('section', group.id);
                  const isExpanded = expandedPanels[panelId] ?? false;
                  const moduleScore = averageScores(
                    group.resources.map((resource) =>
                      getResourceScore(
                        accessibilityByResourceId.get(resource.id),
                      ),
                    ),
                  );

                  return (
                    <div
                      className="overflow-hidden rounded-3xl border border-line bg-white shadow-card"
                      key={group.id}
                    >
                      <h3>
                        <button
                          aria-controls={panelId}
                          aria-expanded={isExpanded}
                          className="flex w-full flex-col gap-3 px-5 py-4 text-left text-ink sm:px-6 lg:flex-row lg:items-center lg:justify-between"
                          onClick={() => togglePanel(panelId)}
                          type="button"
                        >
                          <span className="text-base font-semibold leading-6">
                            {group.section}
                          </span>
                          <span className="flex flex-col gap-2 sm:flex-row sm:items-center">
                            <ScoreBadge score={moduleScore} />
                            <span className="text-sm font-medium text-subtle">
                              {isExpanded ? 'Cerrar' : 'Abrir'} ·{' '}
                              {group.resources.length} recursos
                            </span>
                          </span>
                        </button>
                      </h3>

                      <div
                        className="border-t border-line bg-[var(--color-surface-soft)] p-4 sm:p-5"
                        hidden={!isExpanded}
                        id={panelId}
                      >
                        <ul className="space-y-3">
                          {group.resources.map((resource) => (
                            <ResourceScoreRow
                              accessibilityResult={accessibilityByResourceId.get(
                                resource.id,
                              )}
                              key={resource.id}
                              resource={resource}
                            />
                          ))}
                        </ul>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>

          <div className="flex flex-col gap-3 border-t border-line pt-6 sm:flex-row sm:flex-wrap">
            {jobId ? (
              <button
                className="button-primary w-full sm:w-auto"
                onClick={() =>
                  navigate(`/report/${jobId}${getModeSearch(appMode)}`)
                }
                type="button"
              >
                Obtener informe detallado
              </button>
            ) : null}
            <button
              className="button-secondary w-full sm:w-auto"
              disabled={isRetrying}
              onClick={() => {
                void handleRetryAnalysis();
              }}
              type="button"
            >
              {isRetrying ? 'Reintentando...' : 'Reintentar análisis'}
            </button>
          </div>
        </div>
      )}
    </LayoutSimple>
  );
}
