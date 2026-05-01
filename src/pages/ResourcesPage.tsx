import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';
import {
  fetchResources,
  getResourceDownloadUrl,
  api,
} from '../lib/api';
import type { AppMode, CourseStructure, CourseStructureNode, ResourceListItem } from '../lib/types';
import { getReviewResourceTypeLabel } from '../lib/types';
import {
  getModeSearch,
  isAppMode,
  loadRememberedAppMode,
  rememberAppMode,
} from '../lib/utils';

type BadgeTone = 'ok' | 'warning' | 'danger' | 'neutral';

interface ResourceGroup {
  id: string;
  section: string;
  resources: ResourceListItem[];
}

function getAccessLabel(resource: ResourceListItem) {
  if (resource.accessStatus === 'REQUIERE_INTERACCION') {
    return 'REQUIERE INTERACCIÓN';
  }
  return resource.canAccess && resource.accessStatus === 'OK' ? 'OK' : 'NO ACCEDE';
}

function getAccessTone(resource: ResourceListItem): BadgeTone {
  if (resource.canAccess && resource.accessStatus === 'OK') {
    return 'ok';
  }
  if (
    resource.accessStatus === 'REQUIERE_INTERACCION' ||
    resource.accessStatus === 'FORBIDDEN' ||
    resource.accessStatus === 'TIMEOUT'
  ) {
    return 'warning';
  }
  return 'danger';
}

function getDownloadLabel(resource: ResourceListItem) {
  return resource.canDownload ? 'DESCARGABLE' : 'NO DESCARGABLE';
}

function getDownloadTone(resource: ResourceListItem): BadgeTone {
  if (resource.canDownload) {
    return 'ok';
  }
  return resource.canAccess ? 'neutral' : 'warning';
}

function getStatusClasses(tone: BadgeTone) {
  if (tone === 'ok') {
    return 'border-emerald-200 bg-emerald-50 text-[#166534]';
  }

  if (tone === 'warning') {
    return 'border-amber-200 bg-amber-50 text-[#8a5a00]';
  }

  if (tone === 'neutral') {
    return 'border-slate-200 bg-slate-100 text-slate-700';
  }

  return 'border-rose-200 bg-rose-50 text-danger';
}

function getSectionLabel(resource: ResourceListItem) {
  return resource.modulePath || resource.coursePath || 'Sin sección';
}

function isDownloadable(resource: ResourceListItem, mode: AppMode) {
  return mode === 'offline' && resource.canDownload && Boolean(resource.filePath || resource.localPath || resource.path);
}

function buildGroupsByPath(resources: ResourceListItem[]): ResourceGroup[] {
  const groups = new Map<string, ResourceListItem[]>();

  resources.forEach((resource) => {
    const section = getSectionLabel(resource);
    const existing = groups.get(section);
    if (existing) {
      existing.push(resource);
      return;
    }

    groups.set(section, [resource]);
  });

  return Array.from(groups.entries()).map(([section, sectionResources]) => ({
    id: section,
    section,
    resources: sectionResources,
  }));
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

  return collected;
}

function buildGroupsFromStructure(
  structure: CourseStructure,
  resources: ResourceListItem[],
): ResourceGroup[] {
  const resourcesById = new Map(resources.map((resource) => [resource.id, resource]));
  const groupedResourceIds = new Set<string>();
  const groups: ResourceGroup[] = [];

  structure.organizations.forEach((organization) => {
    const directResources: ResourceListItem[] = [];

    organization.children.forEach((node) => {
      if (node.resourceId && node.children.length === 0) {
        const resource = resourcesById.get(node.resourceId);
        if (resource) {
          directResources.push(resource);
          groupedResourceIds.add(resource.id);
        }
        return;
      }

      const sectionResources = collectNodeResources(node, resourcesById);
      if (sectionResources.length === 0) {
        return;
      }

      sectionResources.forEach((resource) => groupedResourceIds.add(resource.id));
      groups.push({
        id: node.nodeId,
        section: node.title,
        resources: sectionResources,
      });
    });

    if (directResources.length > 0) {
      groups.push({
        id: `${organization.nodeId}-direct`,
        section: organization.title,
        resources: directResources,
      });
    }
  });

  const unplacedResources = structure.unplacedResourceIds
    .map((resourceId) => resourcesById.get(resourceId))
    .filter((resource): resource is ResourceListItem => Boolean(resource));

  unplacedResources.forEach((resource) => groupedResourceIds.add(resource.id));

  if (unplacedResources.length > 0) {
    groups.push({
      id: 'unplaced-resources',
      section: 'Sin sección',
      resources: unplacedResources,
    });
  }

  const remainingResources = resources.filter((resource) => !groupedResourceIds.has(resource.id));
  if (remainingResources.length > 0) {
    groups.push(...buildGroupsByPath(remainingResources));
  }

  return groups;
}

export function ResourcesPage() {
  const navigate = useNavigate();
  const { jobId } = useParams<{ jobId: string }>();
  const [searchParams] = useSearchParams();
  const [resources, setResources] = useState<ResourceListItem[]>([]);
  const [structure, setStructure] = useState<CourseStructure | null>(null);
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [isRetrying, setIsRetrying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const modeParam = searchParams.get('mode');
  const appMode: AppMode = isAppMode(modeParam)
    ? modeParam
    : loadRememberedAppMode() ?? 'offline';

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

    return buildGroupsByPath(resources);
  }, [resources, structure]);
  const accessedCount = useMemo(
    () => resources.filter((resource) => resource.accessStatus === 'OK').length,
    [resources],
  );
  const requiresInteractionCount = useMemo(
    () => resources.filter((resource) => resource.accessStatus === 'REQUIERE_INTERACCION').length,
    [resources],
  );
  const downloadableCount = useMemo(
    () => resources.filter((resource) => resource.canDownload).length,
    [resources],
  );
  const accessibleDownloadableCount = useMemo(
    () => resources.filter((resource) => resource.canAccess && resource.canDownload).length,
    [resources],
  );

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
      navigate(`/analyzing/${jobId}${getModeSearch('offline')}`, { replace: true });
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : 'No hemos podido relanzar el análisis.',
      );
      setIsRetrying(false);
    }
  };

  const toggleSection = (section: string) => {
    setExpandedSections((current) => ({
      ...current,
      [section]: !current[section],
    }));
  };

  return (
    <LayoutSimple
      backLabel="Volver"
      backTo={`/${appMode}${getModeSearch(appMode)}`}
      description="Resumen del acceso a recursos detectados durante el análisis."
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
        <div className="space-y-6">
          <section className="card-panel space-y-3 p-5">
            <h2 className="text-lg font-semibold text-ink">Resumen del acceso</h2>
            <p className="text-base text-ink">
              Se ha accedido a {accessedCount} de {resources.length} recursos.
            </p>
            <p className="text-base text-ink">
              Requieren interacción: {requiresInteractionCount}.
            </p>
            <p className="text-base text-ink">
              Descargables: {downloadableCount} ({accessibleDownloadableCount} accesibles).
            </p>
          </section>

          <section className="space-y-4">
            <h2 className="text-xl font-semibold text-ink">Recursos por módulo o sección</h2>

            {groups.length === 0 ? (
              <div className="card-panel p-6 text-sm text-subtle">
                No hay recursos para mostrar en este análisis.
              </div>
            ) : (
              groups.map((group) => {
                const isExpanded = expandedSections[group.id] ?? false;
                const sectionId = `section-${group.id.replace(/\s+/g, '-').toLowerCase()}`;

                return (
                  <section className="card-panel overflow-hidden" key={group.id}>
                    <h3>
                      <button
                        aria-controls={sectionId}
                        aria-expanded={isExpanded}
                        className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left text-base font-semibold text-ink sm:px-6"
                        onClick={() => toggleSection(group.id)}
                        type="button"
                      >
                        <span>{group.section}</span>
                        <span className="text-sm font-medium text-subtle">
                          {group.resources.length}
                        </span>
                      </button>
                    </h3>

                    <div
                      className="border-t border-line"
                      hidden={!isExpanded}
                      id={sectionId}
                    >
                      <ul className="divide-y divide-line">
                        {group.resources.map((resource) => {
                          const accessLabel = getAccessLabel(resource);
                          const downloadLabel = getDownloadLabel(resource);
                          const downloadable = jobId
                            ? isDownloadable(resource, appMode)
                            : false;

                          return (
                            <li
                              className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6"
                              key={resource.id}
                            >
                              <div className="space-y-2">
                                <p className="text-base font-semibold text-ink">
                                  {resource.title}
                                </p>
                                <div className="flex flex-wrap gap-2 text-sm">
                                  <span
                                    aria-label={`Acceso ${accessLabel}`}
                                    className={`inline-flex rounded-full border px-3 py-1 font-semibold ${getStatusClasses(getAccessTone(resource))}`}
                                  >
                                    {accessLabel}
                                  </span>
                                  <span
                                    aria-label={`Descarga ${downloadLabel}`}
                                    className={`inline-flex rounded-full border px-3 py-1 font-semibold ${getStatusClasses(getDownloadTone(resource))}`}
                                  >
                                    {downloadLabel}
                                  </span>
                                  <span
                                    aria-label={`Tipo ${getReviewResourceTypeLabel(resource.type)}`}
                                    className="inline-flex rounded-full border border-line bg-[#f7faf7] px-3 py-1 font-medium text-subtle"
                                  >
                                    {getReviewResourceTypeLabel(resource.type)}
                                  </span>
                                </div>
                              </div>

                              {downloadable && jobId ? (
                                <a
                                  aria-label={`Descargar ${resource.title}`}
                                  className="button-secondary w-full sm:w-auto"
                                  href={getResourceDownloadUrl(jobId, resource.id)}
                                >
                                  Descargar
                                </a>
                              ) : null}
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  </section>
                );
              })
            )}
          </section>

          <div className="flex flex-col gap-3 sm:flex-row">
            <Link
              className="button-secondary w-full sm:w-auto"
              to={`/${appMode}${getModeSearch(appMode)}`}
            >
              Volver
            </Link>
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
