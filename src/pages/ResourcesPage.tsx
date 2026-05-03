import { useEffect, useMemo, useState } from 'react';
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';
import { fetchResources, getResourceDownloadUrl, api } from '../lib/api';
import type {
  AppMode,
  CourseStructure,
  CourseStructureNode,
  ResourceListItem,
} from '../lib/types';
import { getReviewResourceTypeLabel } from '../lib/types';
import {
  getModeSearch,
  isAppMode,
  loadRememberedAppMode,
  rememberAppMode,
} from '../lib/utils';

type BadgeTone = 'ok' | 'warning' | 'danger' | 'neutral';

interface ResourceTreeNode {
  resource: ResourceListItem;
  children: ResourceTreeNode[];
}

interface ResourceSubsection {
  id: string;
  title: string;
  resources: ResourceListItem[];
}

interface ResourceGroup {
  id: string;
  section: string;
  description?: string;
  isGlobalUnplaced: boolean;
  resources: ResourceListItem[];
  directResources: ResourceListItem[];
  subsections: ResourceSubsection[];
}

interface BackendResourceCounts {
  globalUnplacedCount: number | null;
  noAccessCount: number | null;
}

interface ResourceFilters {
  onlyNoAccess: boolean;
  onlyDownloadable: boolean;
  hideGlobalUnplaced: boolean;
}

const EMPTY_FILTERS: ResourceFilters = {
  onlyNoAccess: false,
  onlyDownloadable: false,
  hideGlobalUnplaced: false,
};

const GLOBAL_UNPLACED_SECTION_LABEL =
  'Recursos globales o no ubicados en la estructura del curso';
const GLOBAL_UNPLACED_SECTION_DESCRIPTION =
  'Recursos incluidos en el paquete, pero no asociados claramente a un módulo o PEC.';

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

function buildGlobalMetadata(isGlobalUnplaced: boolean) {
  return isGlobalUnplaced
    ? {
        description: GLOBAL_UNPLACED_SECTION_DESCRIPTION,
        isGlobalUnplaced,
      }
    : {
        isGlobalUnplaced,
      };
}

function getAccessLabel(resource: ResourceListItem) {
  if (resource.accessStatus === 'REQUIERE_INTERACCION') {
    return 'REQUIERE INTERACCIÓN';
  }

  if (resource.accessStatus === 'REQUIERE_SSO') {
    return 'REQUIERE SSO';
  }

  return resource.canAccess && resource.accessStatus === 'OK'
    ? 'OK'
    : 'NO ACCEDE';
}

function getAccessTone(resource: ResourceListItem): BadgeTone {
  const accessLabel = getAccessLabel(resource);

  if (accessLabel === 'OK') {
    return 'ok';
  }

  if (
    accessLabel === 'REQUIERE INTERACCIÓN' ||
    accessLabel === 'REQUIERE SSO'
  ) {
    return 'warning';
  }

  return 'danger';
}

function getDownloadLabel(resource: ResourceListItem) {
  return resource.canDownload ? 'DESCARGABLE' : 'NO DESCARGABLE';
}

function getDownloadTone(resource: ResourceListItem): BadgeTone {
  return resource.canDownload ? 'ok' : 'neutral';
}

function getStatusClasses(tone: BadgeTone) {
  if (tone === 'ok') {
    return 'border-emerald-200 bg-emerald-50 text-[#166534]';
  }

  if (tone === 'warning') {
    return 'border-amber-200 bg-amber-50 text-[#8a5a00]';
  }

  if (tone === 'neutral') {
    return 'border-slate-200 bg-slate-50 text-slate-700';
  }

  return 'border-rose-200 bg-rose-50 text-danger';
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

function isNoAccessResource(resource: ResourceListItem) {
  return getAccessLabel(resource) === 'NO ACCEDE';
}

function getNoAccessReason(resource: ResourceListItem) {
  if (resource.reasonCode) {
    return resource.reasonCode;
  }

  if (typeof resource.httpStatus === 'number') {
    return `http_${resource.httpStatus}`;
  }

  if (resource.urlStatus) {
    return resource.urlStatus;
  }

  if (resource.accessStatus && resource.accessStatus !== 'OK') {
    return resource.accessStatus.toLocaleLowerCase('es-ES');
  }

  return 'no_access';
}

function getNoAccessDetail(resource: ResourceListItem) {
  return (
    resource.reasonDetail ||
    resource.errorMessage ||
    resource.accessNote ||
    null
  );
}

function hasTechnicalDetails(resource: ResourceListItem) {
  return typeof resource.httpStatus === 'number' || Boolean(resource.finalUrl);
}

function toPanelId(prefix: string, id: string) {
  const normalizedId =
    id.replace(/[^a-zA-Z0-9_-]+/g, '-').replace(/^-|-$/g, '') || 'panel';
  return `${prefix}-${normalizedId.toLowerCase()}`;
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
  directResources: ResourceListItem[],
  subsections: ResourceSubsection[] = [],
): ResourceGroup {
  const section = normalizeSectionName(title);
  const isGlobalUnplaced = section === GLOBAL_UNPLACED_SECTION_LABEL;
  const subsectionResources = subsections.flatMap(
    (subsection) => subsection.resources,
  );
  const resources = uniqueResources([
    ...directResources,
    ...subsectionResources,
  ]);

  return {
    id,
    section,
    ...buildGlobalMetadata(isGlobalUnplaced),
    resources,
    directResources: uniqueResources(directResources),
    subsections,
  };
}

function buildGroupFromStructureNode(
  node: CourseStructureNode,
  resourcesById: Map<string, ResourceListItem>,
): ResourceGroup | null {
  const directResources: ResourceListItem[] = [];
  const subsections: ResourceSubsection[] = [];

  node.children.forEach((childNode) => {
    if (childNode.resourceId && childNode.children.length === 0) {
      const resource = resourcesById.get(childNode.resourceId);
      if (resource) {
        directResources.push(resource);
      }
      return;
    }

    const subsectionResources = collectNodeResources(childNode, resourcesById);
    if (subsectionResources.length > 0) {
      subsections.push({
        id: childNode.nodeId,
        title: normalizeSectionName(childNode.title),
        resources: subsectionResources,
      });
    }
  });

  if (directResources.length === 0 && subsections.length === 0) {
    directResources.push(...collectNodeResources(node, resourcesById));
  }

  const group = createGroup(
    node.nodeId,
    node.title,
    directResources,
    subsections,
  );
  return group.resources.length > 0 ? group : null;
}

function buildGroupsByPath(resources: ResourceListItem[]): ResourceGroup[] {
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
): ResourceGroup[] {
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

      const group = buildGroupFromStructureNode(node, resourcesById);
      if (!group) {
        return;
      }

      group.resources.forEach((resource) =>
        groupedResourceIds.add(resource.id),
      );
      groups.push(group);
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
    .filter((resource): resource is ResourceListItem => Boolean(resource));

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

  if (remainingResources.length > 0) {
    groups.push(...buildGroupsByPath(remainingResources));
  }

  return sortGlobalGroupLast(groups);
}

function buildResourceTree(resources: ResourceListItem[]): ResourceTreeNode[] {
  const nodeMap = new Map<string, ResourceTreeNode>();

  resources.forEach((resource) => {
    nodeMap.set(resource.id, { resource, children: [] });
  });

  const roots: ResourceTreeNode[] = [];

  resources.forEach((resource) => {
    const node = nodeMap.get(resource.id);
    if (!node) {
      return;
    }

    const parentNode = resource.parentResourceId
      ? nodeMap.get(resource.parentResourceId)
      : null;

    if (parentNode && resource.parentResourceId !== resource.id) {
      parentNode.children.push(node);
      return;
    }

    roots.push(node);
  });

  return roots;
}

function resourceMatchesFilters(
  resource: ResourceListItem,
  filters: ResourceFilters,
) {
  if (filters.onlyNoAccess && !isNoAccessResource(resource)) {
    return false;
  }

  if (filters.onlyDownloadable && !resource.canDownload) {
    return false;
  }

  return true;
}

function filterGroup(group: ResourceGroup, filters: ResourceFilters) {
  if (filters.hideGlobalUnplaced && group.isGlobalUnplaced) {
    return null;
  }

  const directResources = group.directResources.filter((resource) =>
    resourceMatchesFilters(resource, filters),
  );
  const subsections = group.subsections
    .map((subsection) => ({
      ...subsection,
      resources: subsection.resources.filter((resource) =>
        resourceMatchesFilters(resource, filters),
      ),
    }))
    .filter((subsection) => subsection.resources.length > 0);
  const resourceIds = new Set([
    ...directResources.map((resource) => resource.id),
    ...subsections.flatMap((subsection) =>
      subsection.resources.map((resource) => resource.id),
    ),
  ]);
  const resources = group.resources.filter((resource) =>
    resourceIds.has(resource.id),
  );

  if (resources.length === 0) {
    return null;
  }

  return {
    ...group,
    resources,
    directResources,
    subsections,
  };
}

function Badge({ children, tone }: { children: string; tone: BadgeTone }) {
  return <span className={`badge ${getStatusClasses(tone)}`}>{children}</span>;
}

function ResourceItem({
  jobId,
  resource,
}: {
  jobId: string | undefined;
  resource: ResourceListItem;
}) {
  const accessLabel = getAccessLabel(resource);
  const isNoAccess = isNoAccessResource(resource);
  const reasonDetail = getNoAccessDetail(resource);
  const showTechnicalDetails = hasTechnicalDetails(resource);

  return (
    <div className="space-y-3 rounded-2xl border border-line bg-white p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-3">
          <p className="break-words text-base font-semibold text-ink">
            {resource.title}
          </p>

          <div className="flex flex-wrap gap-2">
            <Badge tone="neutral">
              {`Tipo: ${getReviewResourceTypeLabel(resource.type)}`}
            </Badge>
            <Badge tone={getAccessTone(resource)}>{accessLabel}</Badge>
            <Badge tone={getDownloadTone(resource)}>
              {getDownloadLabel(resource)}
            </Badge>
          </div>
        </div>

        {resource.canDownload && jobId ? (
          <a
            aria-label={`Descargar ${resource.title}`}
            className="button-secondary w-full shrink-0 sm:w-auto"
            href={getResourceDownloadUrl(jobId, resource.id)}
          >
            Descargar
          </a>
        ) : null}
      </div>

      {isNoAccess ? (
        <div className="space-y-1 text-sm leading-6 text-ink">
          <p>
            <span className="font-semibold">Motivo:</span>{' '}
            {getNoAccessReason(resource)}
          </p>
          {reasonDetail ? (
            <p>
              <span className="font-semibold">Detalle:</span> {reasonDetail}
            </p>
          ) : null}
          {showTechnicalDetails ? (
            <details className="mt-2 rounded-xl border border-line bg-[#f8faf7] px-3 py-2">
              <summary className="cursor-pointer font-semibold text-ink focus:outline-none focus-visible:rounded-md focus-visible:outline focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-[#0f766e]">
                Más detalles
              </summary>
              <dl className="mt-3 space-y-2 text-sm text-subtle">
                {typeof resource.httpStatus === 'number' ? (
                  <div>
                    <dt className="font-semibold text-ink">Estado HTTP</dt>
                    <dd>{resource.httpStatus}</dd>
                  </div>
                ) : null}
                {resource.finalUrl ? (
                  <div>
                    <dt className="font-semibold text-ink">URL final</dt>
                    <dd className="break-all">{resource.finalUrl}</dd>
                  </div>
                ) : null}
              </dl>
            </details>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function ResourceTreeList({
  jobId,
  nodes,
  level = 0,
}: {
  jobId: string | undefined;
  nodes: ResourceTreeNode[];
  level?: number;
}) {
  if (nodes.length === 0) {
    return null;
  }

  return (
    <ul
      className={
        level > 0 ? 'mt-3 space-y-3 border-l border-line pl-4' : 'space-y-3'
      }
    >
      {nodes.map((node) => (
        <li key={node.resource.id}>
          <ResourceItem jobId={jobId} resource={node.resource} />
          {node.children.length > 0 ? (
            <div className="mt-3">
              <p className="mb-2 text-sm font-semibold text-subtle">
                Recursos detectados dentro
              </p>
              <ResourceTreeList
                jobId={jobId}
                level={level + 1}
                nodes={node.children}
              />
            </div>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

export function ResourcesPage() {
  const navigate = useNavigate();
  const { jobId } = useParams<{ jobId: string }>();
  const [searchParams] = useSearchParams();
  const [resources, setResources] = useState<ResourceListItem[]>([]);
  const [structure, setStructure] = useState<CourseStructure | null>(null);
  const [backendCounts, setBackendCounts] = useState<BackendResourceCounts>({
    globalUnplacedCount: null,
    noAccessCount: null,
  });
  const [filters, setFilters] = useState<ResourceFilters>(EMPTY_FILTERS);
  const [expandedPanels, setExpandedPanels] = useState<Record<string, boolean>>(
    {},
  );
  const [isLoading, setIsLoading] = useState(true);
  const [isRetrying, setIsRetrying] = useState(false);
  const [error, setError] = useState<string | null>(null);
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
        const payload = await fetchResources(resolvedJobId);
        if (cancelled) {
          return;
        }

        setResources(payload.resources);
        setStructure(payload.structure);
        setBackendCounts({
          globalUnplacedCount:
            typeof payload.globalUnplacedCount === 'number'
              ? payload.globalUnplacedCount
              : null,
          noAccessCount:
            typeof payload.noAccessCount === 'number'
              ? payload.noAccessCount
              : null,
        });
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

  const groups = useMemo(() => {
    if (structure) {
      return buildGroupsFromStructure(structure, resources);
    }

    return sortGlobalGroupLast(buildGroupsByPath(resources));
  }, [resources, structure]);

  const filteredGroups = useMemo(
    () =>
      groups
        .map((group) => filterGroup(group, filters))
        .filter((group): group is ResourceGroup => Boolean(group)),
    [filters, groups],
  );
  const accessedCount = useMemo(
    () =>
      resources.filter((resource) => getAccessLabel(resource) === 'OK').length,
    [resources],
  );
  const inaccessibleCount = useMemo(
    () => resources.filter(isNoAccessResource).length,
    [resources],
  );
  const requiresSsoCount = useMemo(
    () =>
      resources.filter(
        (resource) => getAccessLabel(resource) === 'REQUIERE SSO',
      ).length,
    [resources],
  );
  const requiresInteractionCount = useMemo(
    () =>
      resources.filter(
        (resource) => getAccessLabel(resource) === 'REQUIERE INTERACCIÓN',
      ).length,
    [resources],
  );
  const downloadableCount = useMemo(
    () => resources.filter((resource) => resource.canDownload).length,
    [resources],
  );
  const accessibleDownloadableCount = useMemo(
    () =>
      resources.filter((resource) => resource.canAccess && resource.canDownload)
        .length,
    [resources],
  );
  const globalUnplacedCount = useMemo(
    () =>
      groups
        .filter((group) => group.isGlobalUnplaced)
        .reduce((total, group) => total + group.resources.length, 0),
    [groups],
  );
  const displayedInaccessibleCount =
    backendCounts.noAccessCount ?? inaccessibleCount;
  const displayedGlobalUnplacedCount =
    backendCounts.globalUnplacedCount ?? globalUnplacedCount;
  const activeFilterCount = Object.values(filters).filter(Boolean).length;

  const summaryItems = [
    {
      label: 'Accedidos',
      value: `${accessedCount} de ${resources.length}`,
      show: true,
    },
    {
      label: 'Descargables',
      value: `${downloadableCount} (${accessibleDownloadableCount} accesibles)`,
      show: true,
    },
    {
      label: 'No accesibles',
      value: String(displayedInaccessibleCount),
      show: true,
    },
    {
      label: 'Requieren SSO',
      value: String(requiresSsoCount),
      show: requiresSsoCount > 0,
    },
    {
      label: 'Requieren interacción',
      value: String(requiresInteractionCount),
      show: requiresInteractionCount > 0,
    },
    {
      label: 'Recursos globales/no ubicados',
      value: String(displayedGlobalUnplacedCount),
      show: displayedGlobalUnplacedCount > 0,
    },
  ].filter((item) => item.show);

  const togglePanel = (panelId: string) => {
    setExpandedPanels((current) => ({
      ...current,
      [panelId]: !current[panelId],
    }));
  };

  const updateFilter = (name: keyof ResourceFilters, checked: boolean) => {
    setFilters((current) => ({
      ...current,
      [name]: checked,
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
      description="Diagnóstico de acceso y descarga de los recursos detectados."
      title="Acceso a recursos"
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
          Cargando recursos del curso…
        </section>
      ) : (
        <div className="space-y-8">
          <section
            aria-live="polite"
            className="rounded-3xl border border-line bg-white p-5 shadow-card sm:p-6"
          >
            <h2 className="text-lg font-semibold text-ink">
              Resumen del acceso
            </h2>
            <dl className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {summaryItems.map((item) => (
                <div
                  className="rounded-2xl border border-line bg-[#f8faf7] p-4"
                  key={item.label}
                >
                  <dt className="text-sm font-medium text-subtle">
                    {item.label}
                  </dt>
                  <dd className="mt-1 text-2xl font-semibold tracking-[-0.03em] text-ink">
                    {item.value}
                  </dd>
                </div>
              ))}
            </dl>
          </section>

          <section className="rounded-3xl border border-line bg-white p-5 shadow-card sm:p-6">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
              <div className="space-y-1">
                <h2 className="text-lg font-semibold text-ink">Filtros</h2>
                <p className="text-sm leading-6 text-subtle">
                  Usa estos controles para revisar incidencias y descargables
                  sin perder contexto.
                </p>
              </div>

              <button
                className="button-secondary w-full sm:w-auto"
                disabled={activeFilterCount === 0}
                onClick={() => setFilters(EMPTY_FILTERS)}
                type="button"
              >
                Limpiar filtros
              </button>
            </div>

            <fieldset className="mt-5">
              <legend className="sr-only">Filtrar recursos</legend>
              <div className="grid gap-3 sm:grid-cols-3">
                <label className="flex cursor-pointer items-start gap-3 rounded-2xl border border-line bg-[#f8faf7] p-4 text-sm font-semibold text-ink">
                  <input
                    checked={filters.onlyNoAccess}
                    className="mt-1 h-5 w-5 accent-[#0f766e]"
                    onChange={(event) =>
                      updateFilter('onlyNoAccess', event.target.checked)
                    }
                    type="checkbox"
                  />
                  <span>Mostrar solo NO ACCEDE</span>
                </label>
                <label className="flex cursor-pointer items-start gap-3 rounded-2xl border border-line bg-[#f8faf7] p-4 text-sm font-semibold text-ink">
                  <input
                    checked={filters.onlyDownloadable}
                    className="mt-1 h-5 w-5 accent-[#0f766e]"
                    onChange={(event) =>
                      updateFilter('onlyDownloadable', event.target.checked)
                    }
                    type="checkbox"
                  />
                  <span>Mostrar solo descargables</span>
                </label>
                <label className="flex cursor-pointer items-start gap-3 rounded-2xl border border-line bg-[#f8faf7] p-4 text-sm font-semibold text-ink">
                  <input
                    checked={filters.hideGlobalUnplaced}
                    className="mt-1 h-5 w-5 accent-[#0f766e]"
                    onChange={(event) =>
                      updateFilter('hideGlobalUnplaced', event.target.checked)
                    }
                    type="checkbox"
                  />
                  <span>Ocultar recursos globales/no ubicados</span>
                </label>
              </div>
            </fieldset>
          </section>

          <section className="space-y-4">
            <div className="space-y-1">
              <h2 className="text-xl font-semibold text-ink">
                Recursos por módulo o sección
              </h2>
              <p className="text-sm leading-6 text-subtle">
                Las secciones se abren y cierran con teclado. Los recursos
                detectados dentro de una página aparecen como hijos cuando el
                inventario lo indica.
              </p>
            </div>

            {filteredGroups.length === 0 ? (
              <div className="card-panel p-6 text-sm text-subtle">
                No hay recursos que coincidan con los filtros actuales.
              </div>
            ) : (
              <div className="space-y-3">
                {filteredGroups.map((group) => {
                  const panelId = toPanelId('section', group.id);
                  const isExpanded = expandedPanels[panelId] ?? false;
                  const sectionDescriptionId = `${panelId}-description`;

                  return (
                    <div
                      className="overflow-hidden rounded-3xl border border-line bg-white shadow-card"
                      key={group.id}
                    >
                      <h3>
                        <button
                          aria-controls={panelId}
                          aria-describedby={
                            group.description ? sectionDescriptionId : undefined
                          }
                          aria-expanded={isExpanded}
                          aria-label={`${isExpanded ? 'Cerrar' : 'Abrir'} sección ${group.section}, ${group.resources.length} recursos`}
                          className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left text-base font-semibold text-ink sm:px-6"
                          onClick={() => togglePanel(panelId)}
                          type="button"
                        >
                          <span>{group.section}</span>
                          <span className="shrink-0 text-sm font-medium text-subtle">
                            {group.resources.length} recursos
                          </span>
                        </button>
                      </h3>
                      {group.description ? (
                        <p
                          className="px-5 pb-4 text-sm leading-6 text-subtle sm:px-6"
                          id={sectionDescriptionId}
                        >
                          {group.description}
                        </p>
                      ) : null}

                      <div
                        className="border-t border-line bg-[#fbfcfa] p-4 sm:p-5"
                        hidden={!isExpanded}
                        id={panelId}
                      >
                        {group.directResources.length > 0 ? (
                          <ResourceTreeList
                            jobId={jobId}
                            nodes={buildResourceTree(group.directResources)}
                          />
                        ) : null}

                        {group.subsections.length > 0 ? (
                          <div className="space-y-3">
                            {group.subsections.map((subsection) => {
                              const subsectionPanelId = toPanelId(
                                'subsection',
                                `${group.id}-${subsection.id}`,
                              );
                              const subsectionExpanded =
                                expandedPanels[subsectionPanelId] ?? false;

                              return (
                                <div
                                  className="overflow-hidden rounded-2xl border border-line bg-white"
                                  key={subsection.id}
                                >
                                  <h4>
                                    <button
                                      aria-controls={subsectionPanelId}
                                      aria-expanded={subsectionExpanded}
                                      aria-label={`${subsectionExpanded ? 'Cerrar' : 'Abrir'} subapartado ${subsection.title}, ${subsection.resources.length} recursos`}
                                      className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left text-sm font-semibold text-ink"
                                      onClick={() =>
                                        togglePanel(subsectionPanelId)
                                      }
                                      type="button"
                                    >
                                      <span>{subsection.title}</span>
                                      <span className="shrink-0 text-xs font-medium uppercase tracking-[0.08em] text-subtle">
                                        {subsection.resources.length} recursos
                                      </span>
                                    </button>
                                  </h4>
                                  <div
                                    className="border-t border-line bg-[#fbfcfa] p-4"
                                    hidden={!subsectionExpanded}
                                    id={subsectionPanelId}
                                  >
                                    <ResourceTreeList
                                      jobId={jobId}
                                      nodes={buildResourceTree(
                                        subsection.resources,
                                      )}
                                    />
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        ) : null}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>

          <div className="flex flex-col gap-3 border-t border-line pt-6 sm:flex-row sm:flex-wrap">
            <Link
              className="button-secondary w-full sm:w-auto"
              to={`/${appMode}${getModeSearch(appMode)}`}
            >
              Volver
            </Link>
            {jobId ? (
              <Link
                className="button-secondary w-full sm:w-auto"
                to={`/report/${jobId}${getModeSearch(appMode)}`}
              >
                Ver informe
              </Link>
            ) : null}
            <button
              className="button-primary w-full sm:w-auto"
              disabled={isRetrying}
              onClick={() => {
                void handleRetryAnalysis();
              }}
              type="button"
            >
              {isRetrying ? 'Reintentando…' : 'Reintentar análisis'}
            </button>
          </div>
        </div>
      )}
    </LayoutSimple>
  );
}
