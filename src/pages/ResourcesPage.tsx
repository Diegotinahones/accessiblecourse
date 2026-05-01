import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';
import {
  fetchResources,
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
  return resource.canAccess && resource.accessStatus === 'OK' ? 'OK' : 'NO ACCEDE';
}

function getAccessTone(resource: ResourceListItem): BadgeTone {
  if (resource.canAccess && resource.accessStatus === 'OK') {
    return 'ok';
  }
  return 'danger';
}

function getDownloadLabel(resource: ResourceListItem) {
  return resource.canDownload ? 'sí' : 'no';
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

function isNoAccess(resource: ResourceListItem) {
  return !(resource.canAccess && resource.accessStatus === 'OK');
}

function getReasonCode(resource: ResourceListItem) {
  if (resource.reasonCode) {
    return resource.reasonCode;
  }

  if (
    resource.accessStatus === 'REQUIERE_INTERACCION' ||
    resource.accessStatus === 'REQUIERE_SSO'
  ) {
    return resource.accessStatus;
  }

  const normalizedUrlStatus = resource.urlStatus?.trim().toLowerCase();
  if (normalizedUrlStatus === 'timeout') {
    return 'timeout';
  }

  const statusCode = resource.accessStatusCode ?? resource.httpStatus;
  if (statusCode === 404 || normalizedUrlStatus === '404') {
    return '404_not_found';
  }
  if (statusCode === 401 || statusCode === 403 || normalizedUrlStatus === '403') {
    return 'forbidden';
  }
  if (statusCode) {
    return `http_${statusCode}`;
  }

  if (resource.accessStatus && resource.accessStatus !== 'OK') {
    return resource.accessStatus;
  }

  return 'no_accede';
}

function getReasonDetail(resource: ResourceListItem) {
  return resource.reasonDetail ?? resource.errorMessage ?? resource.accessNote ?? resource.notes;
}

function isIgnoredOrNoiseResource(resource: ResourceListItem) {
  const notes = resource.notes?.toLowerCase() ?? '';
  const reference = (resource.sourceUrl ?? resource.url ?? resource.filePath ?? resource.path ?? '').trim().toLowerCase();

  return (
    notes.includes('ignored') ||
    notes.includes('ignorado') ||
    notes.includes('ruido') ||
    reference.startsWith('#') ||
    reference.startsWith('mailto:') ||
    reference.startsWith('tel:') ||
    reference.startsWith('javascript:') ||
    reference.startsWith('data:')
  );
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
  const [hideIgnoredResources, setHideIgnoredResources] = useState(true);
  const [showOnlyNoAccess, setShowOnlyNoAccess] = useState(false);
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

  const visibleResources = useMemo(
    () =>
      resources.filter((resource) => {
        if (hideIgnoredResources && isIgnoredOrNoiseResource(resource)) {
          return false;
        }

        if (showOnlyNoAccess && !isNoAccess(resource)) {
          return false;
        }

        return true;
      }),
    [hideIgnoredResources, resources, showOnlyNoAccess],
  );

  const groups = useMemo(() => {
    if (structure) {
      return buildGroupsFromStructure(structure, visibleResources);
    }

    return buildGroupsByPath(visibleResources);
  }, [structure, visibleResources]);
  const accessedCount = useMemo(
    () => visibleResources.filter((resource) => !isNoAccess(resource)).length,
    [visibleResources],
  );
  const downloadableCount = useMemo(
    () => visibleResources.filter((resource) => resource.canDownload).length,
    [visibleResources],
  );
  const summaryText = useMemo(
    () =>
      `Se ha accedido a ${accessedCount} de ${visibleResources.length} recursos. Descargables: ${downloadableCount}.`,
    [accessedCount, downloadableCount, visibleResources.length],
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
          <section aria-atomic="true" aria-live="polite" className="card-panel space-y-3 p-5">
            <h2 className="text-lg font-semibold text-ink">Resumen del acceso</h2>
            <p className="text-base text-ink">{summaryText}</p>
          </section>

          <fieldset className="card-panel space-y-4 p-5">
            <legend className="text-lg font-semibold text-ink">Filtros</legend>
            <label className="flex items-start gap-3 text-base text-ink">
              <input
                checked={hideIgnoredResources}
                className="mt-1 h-5 w-5 accent-[#205e3c]"
                onChange={(event) => setHideIgnoredResources(event.target.checked)}
                type="checkbox"
              />
              <span>Ocultar recursos ignorados/ruido</span>
            </label>
            <label className="flex items-start gap-3 text-base text-ink">
              <input
                checked={showOnlyNoAccess}
                className="mt-1 h-5 w-5 accent-[#205e3c]"
                onChange={(event) => setShowOnlyNoAccess(event.target.checked)}
                type="checkbox"
              />
              <span>Mostrar solo NO ACCEDE</span>
            </label>
          </fieldset>

          <section className="space-y-4">
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
                    <h2>
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
                    </h2>

                    <div
                      className="border-t border-line"
                      hidden={!isExpanded}
                      id={sectionId}
                    >
                      <ul className="divide-y divide-line">
                        {group.resources.map((resource) => {
                          const accessLabel = getAccessLabel(resource);
                          const downloadLabel = getDownloadLabel(resource);
                          const noAccess = isNoAccess(resource);
                          const reasonCode = noAccess ? getReasonCode(resource) : null;
                          const reasonDetail = noAccess ? getReasonDetail(resource) : null;

                          return (
                            <li
                              className="px-5 py-4 sm:px-6"
                              key={resource.id}
                            >
                              <div className="space-y-2">
                                <h3 className="text-base font-semibold text-ink">
                                  {resource.title}
                                </h3>
                                <dl className="grid gap-2 text-sm text-ink sm:grid-cols-3">
                                  <div>
                                    <dt className="font-semibold">Tipo</dt>
                                    <dd>{getReviewResourceTypeLabel(resource.type)}</dd>
                                  </div>
                                  <div>
                                    <dt className="font-semibold">Estado</dt>
                                    <dd>
                                      <span
                                        className={`inline-flex rounded-full border px-3 py-1 font-semibold ${getStatusClasses(getAccessTone(resource))}`}
                                      >
                                        {accessLabel}
                                      </span>
                                    </dd>
                                  </div>
                                  <div>
                                    <dt className="font-semibold">Descargable</dt>
                                    <dd>
                                      <span
                                        className={`inline-flex rounded-full border px-3 py-1 font-semibold ${getStatusClasses(getDownloadTone(resource))}`}
                                      >
                                        {downloadLabel}
                                      </span>
                                    </dd>
                                  </div>
                                </dl>

                                {noAccess && reasonCode ? (
                                  <div className="space-y-2 text-sm text-ink">
                                    <p>
                                      <span className="font-semibold">Motivo:</span>{' '}
                                      {reasonCode}
                                    </p>
                                    {reasonDetail ? (
                                      <details className="rounded-xl border border-line bg-[#f7faf7] px-4 py-3">
                                        <summary className="cursor-pointer font-semibold">
                                          Más detalles
                                        </summary>
                                        <p className="mt-2 leading-6 text-subtle">
                                          {reasonDetail}
                                        </p>
                                      </details>
                                    ) : null}
                                  </div>
                                ) : null}

                              </div>
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
