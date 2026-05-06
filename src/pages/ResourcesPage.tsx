import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';
import {
  api,
  fetchAccessibility,
  fetchResources,
  getResourceDownloadUrl,
} from '../lib/api';
import type {
  AccessibilityCheckStatus,
  AccessibilityResource,
  AccessibilityResourceKind,
  AccessibilityResponse,
  AccessibilitySummary,
  AppMode,
  CourseStructure,
  CourseStructureNode,
  ResourceListItem,
} from '../lib/types';
import { getReviewResourceTypeLabel } from '../lib/types';
import {
  classNames,
  getModeSearch,
  isAppMode,
  loadRememberedAppMode,
  rememberAppMode,
} from '../lib/utils';

type BadgeTone = 'success' | 'warning' | 'danger' | 'neutral';
type PriorityLevel = 'high' | 'medium' | 'low' | 'notAnalyzable';

interface ResourceGroup {
  id: string;
  section: string;
  description?: string;
  isGlobalUnplaced: boolean;
  resources: ResourceListItem[];
}

const GLOBAL_UNPLACED_SECTION_LABEL =
  'Recursos globales o no ubicados en la estructura del curso';
const GLOBAL_UNPLACED_SECTION_DESCRIPTION =
  'Recursos incluidos en el paquete, pero no asociados claramente a un módulo o PEC.';

const EMPTY_ACCESSIBILITY_SUMMARY: AccessibilitySummary = {
  htmlResourcesAnalyzed: 0,
  pdfResourcesAnalyzed: 0,
  wordResourcesAnalyzed: 0,
  videoResourcesAnalyzed: 0,
  pass: 0,
  warning: 0,
  fail: 0,
  notApplicable: 0,
  errors: 0,
};

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
  const isGlobalUnplaced = section === GLOBAL_UNPLACED_SECTION_LABEL;

  return {
    id,
    section,
    description: isGlobalUnplaced
      ? GLOBAL_UNPLACED_SECTION_DESCRIPTION
      : undefined,
    isGlobalUnplaced,
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

function getKindFromValue(
  value: string | null | undefined,
): AccessibilityResourceKind | null {
  const normalizedValue = value
    ?.trim()
    .toUpperCase()
    .replace(/\s+/g, '_')
    .replace(/-/g, '_');

  if (!normalizedValue) {
    return null;
  }

  if (
    normalizedValue === 'PDF' ||
    normalizedValue.includes('APPLICATION/PDF') ||
    normalizedValue.endsWith('.PDF')
  ) {
    return 'PDF';
  }

  if (
    normalizedValue === 'DOCX' ||
    normalizedValue === 'WORD' ||
    normalizedValue.includes('WORDPROCESSINGML') ||
    normalizedValue.includes('MSWORD') ||
    normalizedValue.endsWith('.DOCX')
  ) {
    return 'WORD';
  }

  if (
    normalizedValue === 'VIDEO' ||
    normalizedValue.includes('VIDEO') ||
    normalizedValue.includes('YOUTUBE') ||
    normalizedValue.includes('YOUTU_BE') ||
    normalizedValue.includes('VIMEO') ||
    normalizedValue.includes('KALTURA') ||
    normalizedValue.includes('PANOPTO') ||
    normalizedValue.endsWith('.MP4') ||
    normalizedValue.endsWith('.WEBM') ||
    normalizedValue.endsWith('.MOV')
  ) {
    return 'VIDEO';
  }

  if (
    normalizedValue === 'WEB' ||
    normalizedValue === 'HTML' ||
    normalizedValue.includes('TEXT/HTML') ||
    normalizedValue.endsWith('.HTML') ||
    normalizedValue.endsWith('.HTM')
  ) {
    return 'HTML';
  }

  return null;
}

function getResourceAccessibilityKind(
  resource: ResourceListItem,
  accessibilityResult: AccessibilityResource | undefined,
) {
  const documentKind = [
    resource.type,
    resource.core.type,
    resource.resourceType,
    resource.mimeType,
    resource.filename,
    resource.path,
    resource.filePath,
    resource.localPath,
    resource.core.localPath,
    resource.downloadUrl,
    resource.sourceUrl,
    resource.core.sourceUrl,
    resource.url,
  ]
    .map(getKindFromValue)
    .find((kind) => kind === 'PDF' || kind === 'WORD');

  if (documentKind === 'PDF' || documentKind === 'WORD') {
    return documentKind;
  }

  const hasVideoIndicator = Boolean(
    resource.provider ||
    resource.videoUrl ||
    resource.embedUrl ||
    resource.iframe,
  );
  const videoKind = [
    resource.type,
    resource.core.type,
    resource.resourceType,
    resource.provider,
    resource.videoUrl,
    resource.embedUrl,
    resource.iframe,
    resource.path,
    resource.filePath,
    resource.localPath,
    resource.core.localPath,
    resource.downloadUrl,
    resource.sourceUrl,
    resource.core.sourceUrl,
    resource.url,
  ]
    .map(getKindFromValue)
    .find((kind) => kind === 'VIDEO');

  if (videoKind || hasVideoIndicator) {
    return 'VIDEO';
  }

  const htmlKind = [
    resource.type,
    resource.core.type,
    resource.resourceType,
    resource.contentKind,
    resource.analysisCategory,
    resource.htmlPath,
    resource.core.htmlPath,
    resource.url,
  ]
    .map(getKindFromValue)
    .find((kind) => kind === 'HTML');

  return htmlKind ?? accessibilityResult?.kind ?? 'OTHER';
}

function getAccessLabel(resource: ResourceListItem) {
  if (resource.accessStatus === 'REQUIERE_INTERACCION') {
    return 'REQUIERE INTERACCIÓN';
  }

  if (resource.accessStatus === 'REQUIERE_SSO') {
    return 'REQUIERE SSO';
  }

  if (resource.accessStatus === 'NO_ANALIZABLE') {
    return 'NO ANALIZABLE';
  }

  return resource.canAccess && resource.accessStatus === 'OK'
    ? 'OK'
    : 'NO ACCEDE';
}

function isNoAccessResource(resource: ResourceListItem) {
  return getAccessLabel(resource) === 'NO ACCEDE';
}

function getBadgeClasses(tone: BadgeTone) {
  if (tone === 'success') {
    return 'border-emerald-200 bg-emerald-50 text-[#166534]';
  }

  if (tone === 'warning') {
    return 'border-amber-200 bg-amber-50 text-[#8a5a00]';
  }

  if (tone === 'danger') {
    return 'border-rose-200 bg-rose-50 text-danger';
  }

  return 'border-slate-200 bg-slate-50 text-slate-700';
}

function getAccessTone(resource: ResourceListItem): BadgeTone {
  const label = getAccessLabel(resource);

  if (label === 'OK') {
    return 'success';
  }

  if (label === 'NO ACCEDE') {
    return 'danger';
  }

  return 'warning';
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

function getPriority(score: number | null): PriorityLevel {
  if (score === null) {
    return 'notAnalyzable';
  }

  if (score >= 80) {
    return 'low';
  }

  if (score >= 60) {
    return 'medium';
  }

  return 'high';
}

function getPriorityLabel(priority: PriorityLevel) {
  if (priority === 'low') {
    return 'Prioridad baja';
  }

  if (priority === 'medium') {
    return 'Prioridad media';
  }

  if (priority === 'high') {
    return 'Prioridad alta';
  }

  return 'No analizable';
}

function getPriorityTone(priority: PriorityLevel): BadgeTone {
  if (priority === 'low') {
    return 'success';
  }

  if (priority === 'medium') {
    return 'warning';
  }

  if (priority === 'high') {
    return 'danger';
  }

  return 'neutral';
}

function getScoreClass(score: number | null) {
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

function formatScore(score: number | null) {
  return score === null ? 'Sin puntuación' : `${score}/100`;
}

function hasChecks(accessibilityResult: AccessibilityResource | undefined) {
  return Boolean(accessibilityResult?.checks.length);
}

function isNonAnalyzableResource(
  resource: ResourceListItem,
  accessibilityResult: AccessibilityResource | undefined,
) {
  return !hasChecks(accessibilityResult) || getAccessLabel(resource) !== 'OK';
}

function buildPriorityRecommendations(
  accessibility: AccessibilityResponse | null,
  resources: ResourceListItem[],
) {
  const recommendations: string[] = [];
  const resourcesById = new Map(
    resources.map((resource) => [resource.id, resource]),
  );

  function kindHasIssue(kind: AccessibilityResourceKind) {
    return (accessibility?.resources ?? []).some((result) => {
      const resource = resourcesById.get(result.resourceId);
      const resolvedKind = resource
        ? getResourceAccessibilityKind(resource, result)
        : result.kind;

      return (
        resolvedKind === kind &&
        result.checks.some(
          (check) => check.status === 'FAIL' || check.status === 'WARNING',
        )
      );
    });
  }

  if (kindHasIssue('HTML')) {
    recommendations.push(
      'Definir idioma principal y estructura semántica en páginas HTML.',
    );
  }

  if (kindHasIssue('PDF')) {
    recommendations.push(
      'Exportar PDF como documentos etiquetados y revisar el orden de lectura.',
    );
  }

  if (kindHasIssue('WORD')) {
    recommendations.push(
      'Usar estilos de título y texto alternativo en documentos Word.',
    );
  }

  if (kindHasIssue('VIDEO')) {
    recommendations.push(
      'Revisar subtítulos, transcripción y proveedor de los vídeos.',
    );
  }

  if (resources.some(isNoAccessResource)) {
    recommendations.push(
      'Corregir enlaces rotos o permisos de recursos que no se pueden acceder.',
    );
  }

  const fallbackRecommendations = [
    'Priorizar los recursos con puntuación baja antes de publicar el aula.',
    'Revisar el informe detallado para confirmar las evidencias automáticas.',
    'Validar manualmente los recursos no analizables o que requieren SSO.',
  ];

  return [...recommendations, ...fallbackRecommendations].slice(0, 3);
}

function Badge({ children, tone }: { children: string; tone: BadgeTone }) {
  return (
    <span className={classNames('badge', getBadgeClasses(tone))}>
      {children}
    </span>
  );
}

function MetricCard({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <article className="rounded-2xl border border-line bg-white p-4 shadow-card">
      <p className="text-sm font-medium text-subtle">{label}</p>
      <p className="mt-2 text-3xl font-semibold tracking-[-0.04em] text-ink">
        {value}
      </p>
    </article>
  );
}

function ResourceRow({
  accessibilityResult,
  jobId,
  resource,
}: {
  accessibilityResult: AccessibilityResource | undefined;
  jobId: string | undefined;
  resource: ResourceListItem;
}) {
  const score = getResourceScore(accessibilityResult);
  const priority = getPriority(score);
  const resourceKind = getResourceAccessibilityKind(
    resource,
    accessibilityResult,
  );

  return (
    <li className="rounded-2xl border border-line bg-white p-4">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <h4 className="break-words text-base font-semibold text-ink">
            {resource.title}
          </h4>
          <p className="mt-1 text-sm text-subtle">
            Tipo: {getReviewResourceTypeLabel(resource.type)}
            {resourceKind !== 'OTHER'
              ? ` · Análisis ${resourceKind === 'WORD' ? 'Word' : resourceKind}`
              : ''}
          </p>
        </div>

        <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center lg:justify-end">
          <span
            className={classNames(
              'text-sm font-semibold',
              getScoreClass(score),
            )}
          >
            Score: {formatScore(score)}
          </span>
          <Badge tone={getPriorityTone(priority)}>
            {getPriorityLabel(priority)}
          </Badge>
          <Badge tone={getAccessTone(resource)}>
            {`Acceso: ${getAccessLabel(resource)}`}
          </Badge>
          {resource.canDownload && jobId ? (
            <a
              aria-label={`Descargar ${resource.title}`}
              className="button-secondary min-h-10 px-4 py-2 text-sm"
              href={getResourceDownloadUrl(jobId, resource.id)}
            >
              Descargar
            </a>
          ) : null}
        </div>
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
                : 'No hemos podido cargar el análisis automático de accesibilidad.',
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
  const globalPriority = getPriority(globalScore);
  const accessibilitySummary =
    accessibility?.summary ?? EMPTY_ACCESSIBILITY_SUMMARY;
  const analyzedResourceCount = resources.filter((resource) =>
    hasChecks(accessibilityByResourceId.get(resource.id)),
  ).length;
  const criticalCount =
    accessibilitySummary.fail +
    accessibilitySummary.errors +
    resources.filter(isNoAccessResource).length;
  const nonAnalyzableCount = resources.filter((resource) =>
    isNonAnalyzableResource(
      resource,
      accessibilityByResourceId.get(resource.id),
    ),
  ).length;
  const warningCount = accessibilitySummary.warning;
  const downloadableCount = resources.filter(
    (resource) => resource.canDownload,
  ).length;
  const recommendations = buildPriorityRecommendations(
    accessibility,
    resources,
  );

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
      description="Una vista rápida de puntuación, prioridades y recomendaciones."
      showTokenButton={false}
      title="Análisis ejecutivo"
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
          Cargando resultados del análisis…
        </section>
      ) : (
        <div className="space-y-8">
          <section
            aria-live="polite"
            className="grid gap-5 rounded-3xl border border-line bg-white p-6 shadow-card lg:grid-cols-[1.2fr_1fr]"
          >
            <div className="space-y-4">
              <p className="text-sm font-semibold uppercase tracking-[0.12em] text-subtle">
                Puntuación de accesibilidad analizada
              </p>
              <p
                className={classNames(
                  'text-6xl font-semibold tracking-[-0.06em] sm:text-7xl',
                  getScoreClass(globalScore),
                )}
              >
                {formatScore(globalScore)}
              </p>
              <Badge tone={getPriorityTone(globalPriority)}>
                {getPriorityLabel(globalPriority)}
              </Badge>
            </div>

            <div className="flex flex-col justify-center space-y-3 text-base leading-7 text-subtle">
              {accessibilityError ? (
                <p className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-[#8a5a00]">
                  No se pudo cargar el análisis automático de accesibilidad:{' '}
                  {accessibilityError}
                </p>
              ) : null}
              <p>
                Se han analizado {analyzedResourceCount} recursos de{' '}
                {resources.length} detectados.
              </p>
              <p>El detalle completo está disponible en el informe.</p>
            </div>
          </section>

          <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
            <h2 className="sr-only">Resumen ejecutivo</h2>
            <MetricCard
              label="Recursos analizados"
              value={`${analyzedResourceCount}/${resources.length}`}
            />
            <MetricCard label="Incidencias críticas" value={criticalCount} />
            <MetricCard label="Avisos" value={warningCount} />
            <MetricCard
              label="Recursos no analizables"
              value={nonAnalyzableCount}
            />
            <MetricCard label="Descargables" value={downloadableCount} />
          </section>

          <section className="rounded-3xl border border-line bg-white p-6 shadow-card">
            <h2 className="text-xl font-semibold tracking-[-0.03em] text-ink">
              Recomendaciones prioritarias
            </h2>
            <ol className="mt-5 space-y-3">
              {recommendations.map((recommendation, index) => (
                <li
                  className="flex gap-4 rounded-2xl border border-line bg-[var(--color-surface-soft)] p-4"
                  key={recommendation}
                >
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--uoc-blue)] text-sm font-semibold text-white">
                    {index + 1}
                  </span>
                  <span className="text-base leading-7 text-ink">
                    {recommendation}
                  </span>
                </li>
              ))}
            </ol>
          </section>

          <section className="space-y-4">
            <div className="space-y-1">
              <h2 className="text-xl font-semibold tracking-[-0.03em] text-ink">
                Módulos y recursos
              </h2>
              <p className="text-sm leading-6 text-subtle">
                Abre cada módulo para ver una fila resumida por recurso. El
                detalle técnico queda reservado para el informe.
              </p>
            </div>

            {groups.length === 0 ? (
              <div className="card-panel p-6 text-sm text-subtle">
                No hay recursos detectados para mostrar.
              </div>
            ) : (
              <div className="space-y-3">
                {groups.map((group) => {
                  const panelId = toPanelId('section', group.id);
                  const isExpanded = expandedPanels[panelId] ?? false;
                  const sectionDescriptionId = `${panelId}-description`;
                  const moduleScore = averageScores(
                    group.resources.map((resource) =>
                      getResourceScore(
                        accessibilityByResourceId.get(resource.id),
                      ),
                    ),
                  );
                  const modulePriority = getPriority(moduleScore);

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
                          className="flex w-full flex-col gap-3 px-5 py-4 text-left text-ink sm:px-6 lg:flex-row lg:items-center lg:justify-between"
                          onClick={() => togglePanel(panelId)}
                          type="button"
                        >
                          <span className="text-base font-semibold">
                            {group.section} — {formatScore(moduleScore)} —{' '}
                            {getPriorityLabel(modulePriority)}
                          </span>
                          <span className="text-sm font-medium text-subtle">
                            {isExpanded ? 'Cerrar módulo' : 'Abrir módulo'} ·{' '}
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
                        className="border-t border-line bg-[var(--color-surface-soft)] p-4 sm:p-5"
                        hidden={!isExpanded}
                        id={panelId}
                      >
                        <ul className="space-y-3">
                          {group.resources.map((resource) => (
                            <ResourceRow
                              accessibilityResult={accessibilityByResourceId.get(
                                resource.id,
                              )}
                              jobId={jobId}
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
            <button
              className="button-secondary w-full sm:w-auto"
              onClick={() => navigate(`/${appMode}${getModeSearch(appMode)}`)}
              type="button"
            >
              Volver
            </button>
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
              {isRetrying ? 'Reintentando…' : 'Reintentar análisis'}
            </button>
          </div>
        </div>
      )}
    </LayoutSimple>
  );
}
