import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { LayoutSimple } from '../components/LayoutSimple';
import {
  api,
  fetchAccessibility,
  fetchExecutiveSummary,
  fetchResources,
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
  ExecutiveModule,
  ExecutiveResource,
  ExecutiveSummary,
  JobStatus,
  ResourceListItem,
  ResourceListResponse,
} from '../lib/types';
import {
  classNames,
  getModeSearch,
  isAppMode,
  loadRememberedAppMode,
  rememberAppMode,
} from '../lib/utils';

type PriorityLevel = 'high' | 'medium' | 'low' | 'notAnalyzable';

interface ResourceGroup {
  id: string;
  section: string;
  isGlobalUnplaced: boolean;
  resources: ResourceListItem[];
}

interface ExecutiveResourceGroup {
  id: string;
  section: string;
  score: number | null;
  priority: PriorityLevel | null;
  resourceCount: number;
  analyzedCount: number;
  resources: ExecutiveResource[];
}

interface ResourceFilters {
  onlyNoAccess: boolean;
  onlyDownloadable: boolean;
  onlyFailures: boolean;
  onlyWarnings: boolean;
  onlyHtml: boolean;
  onlyPdf: boolean;
  onlyWord: boolean;
  onlyVideo: boolean;
  onlyNotebook: boolean;
}

const GLOBAL_UNPLACED_SECTION_LABEL =
  'Recursos globales o no ubicados en la estructura del curso';

const EMPTY_FILTERS: ResourceFilters = {
  onlyNoAccess: false,
  onlyDownloadable: false,
  onlyFailures: false,
  onlyWarnings: false,
  onlyHtml: false,
  onlyPdf: false,
  onlyWord: false,
  onlyVideo: false,
  onlyNotebook: false,
};

const EMPTY_ACCESSIBILITY_SUMMARY: AccessibilitySummary = {
  htmlResourcesAnalyzed: 0,
  pdfResourcesAnalyzed: 0,
  wordResourcesAnalyzed: 0,
  videoResourcesAnalyzed: 0,
  notebookResourcesAnalyzed: 0,
  pass: 0,
  warning: 0,
  fail: 0,
  notApplicable: 0,
  errors: 0,
};

function getResourceNoun(count: number) {
  return count === 1 ? 'recurso' : 'recursos';
}

function formatResourceCount(count: number) {
  return `${count} ${getResourceNoun(count)}`;
}

function getAnalyzedResourceLabel(count: number, descriptor: string) {
  const resourceLabel = count === 1 ? 'Recurso' : 'Recursos';
  const analyzedLabel = count === 1 ? 'analizado' : 'analizados';

  return `${resourceLabel} ${descriptor} ${analyzedLabel}`;
}

function normalizeCourseTitleCandidate(value: string | null | undefined) {
  const trimmedValue = value?.trim();
  return trimmedValue || null;
}

function isLikelyCompleteCourseTitle(value: string) {
  return (
    value.length > 8 &&
    (value.includes(' - ') ||
      value.includes(' – ') ||
      value.includes(' — ') ||
      /\s/.test(value))
  );
}

function isLikelyAbbreviatedCourseTitle(value: string) {
  return value.length <= 8 && !/\s/.test(value);
}

function resolveCourseTitle({
  access,
  accessibility,
  executiveSummary,
  job,
}: {
  access: ResourceListResponse | null;
  accessibility: AccessibilityResponse | null;
  executiveSummary: ExecutiveSummary | null;
  job: JobStatus | null;
}) {
  const candidates = [
    executiveSummary?.courseTitle,
    executiveSummary?.courseName,
    access?.courseTitle,
    access?.courseName,
    accessibility?.courseTitle,
    accessibility?.courseName,
    job?.courseTitle,
  ]
    .map(normalizeCourseTitleCandidate)
    .filter((candidate): candidate is string => Boolean(candidate));
  const completeCandidate = candidates.find(isLikelyCompleteCourseTitle);
  const firstCandidate = candidates[0];

  if (completeCandidate) {
    return completeCandidate;
  }

  if (firstCandidate && isLikelyAbbreviatedCourseTitle(firstCandidate)) {
    const longerCandidate = candidates.find(
      (candidate) => candidate.length > firstCandidate.length,
    );

    if (longerCandidate) {
      return longerCandidate;
    }
  }

  return firstCandidate ?? 'Curso analizado';
}

function normalizeComparableText(value: string | null | undefined) {
  return (
    value
      ?.trim()
      .toLocaleLowerCase('es-ES')
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '') ?? ''
  );
}

function normalizeUnknownText(value: unknown) {
  if (typeof value === 'string' || typeof value === 'number') {
    return String(value);
  }

  if (value && typeof value === 'object') {
    return JSON.stringify(value);
  }

  return null;
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

function getKindFromValue(value: unknown): AccessibilityResourceKind | null {
  const normalizedValue = normalizeUnknownText(value)
    ?.trim()
    .toUpperCase()
    .replace(/\s+/g, '_')
    .replace(/-/g, '_');

  if (!normalizedValue) {
    return null;
  }

  if (
    normalizedValue === 'NOTEBOOK' ||
    normalizedValue === 'IPYNB' ||
    normalizedValue.includes('JUPYTER') ||
    normalizedValue.includes('NOTEBOOK') ||
    normalizedValue.includes('IPYNB') ||
    normalizedValue.endsWith('.IPYNB')
  ) {
    return 'NOTEBOOK';
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
    normalizedValue.includes('CONTENTKIND":"HTML') ||
    normalizedValue.endsWith('.HTML') ||
    normalizedValue.endsWith('.HTM')
  ) {
    return 'HTML';
  }

  return null;
}

function getResourceKind(
  resource: ResourceListItem,
  accessibilityResult: AccessibilityResource | undefined,
) {
  const resourceRecord = resource as unknown as Record<string, unknown>;
  const coreRecord = resource.core as unknown as Record<string, unknown>;
  const detectedKind = [
    accessibilityResult?.kind,
    resource.type,
    resource.core.type,
    resource.resourceType,
    resource.mimeType,
    resource.filename,
    resource.contentKind,
    resource.analysisCategory,
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
    resourceRecord.metadata,
    resourceRecord.content_kind,
    resourceRecord.kind,
    coreRecord.metadata,
  ]
    .map(getKindFromValue)
    .find(Boolean);

  return detectedKind ?? accessibilityResult?.kind ?? 'OTHER';
}

function getResourceTypeLabel(kind: AccessibilityResourceKind) {
  if (kind === 'HTML') {
    return 'Página web';
  }

  if (kind === 'PDF') {
    return 'PDF';
  }

  if (kind === 'WORD') {
    return 'Word';
  }

  if (kind === 'VIDEO') {
    return 'Vídeo';
  }

  if (kind === 'NOTEBOOK') {
    return 'Notebook';
  }

  return 'Otro';
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

function normalizeAccessLabel(value: string | null | undefined) {
  const normalizedValue = normalizeComparableText(value);

  if (
    normalizedValue === 'requiere_interaccion' ||
    normalizedValue.includes('interaccion') ||
    normalizedValue.includes('interaction')
  ) {
    return 'REQUIERE INTERACCIÓN';
  }

  if (
    normalizedValue === 'requiere_sso' ||
    normalizedValue.includes('sso') ||
    normalizedValue.includes('auth')
  ) {
    return 'REQUIERE SSO';
  }

  if (
    normalizedValue === 'no_analizable' ||
    normalizedValue.includes('not_scored')
  ) {
    return 'NO ANALIZABLE';
  }

  if (
    normalizedValue === 'ok' ||
    normalizedValue === 'pass' ||
    normalizedValue === 'accessible'
  ) {
    return 'OK';
  }

  return 'NO ACCEDE';
}

function isNoAccessResource(resource: ResourceListItem) {
  return getAccessLabel(resource) === 'NO ACCEDE';
}

function normalizeScore(score: number | null | undefined) {
  if (typeof score !== 'number' || Number.isNaN(score)) {
    return null;
  }

  return Math.round(Math.max(0, Math.min(100, score)));
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
  const backendScore = normalizeScore(accessibilityResult?.score);
  if (backendScore !== null) {
    return backendScore;
  }

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

type GlobalScoreResolution = {
  value: number | null;
  source: string | null;
};

type GlobalPriorityResolution = {
  value: PriorityLevel | null;
  rawValue: string | null;
  source: string | null;
};

function resolveBackendGlobalScore({
  access,
  accessibility,
  executiveSummary,
}: {
  access: ResourceListResponse | null;
  accessibility: AccessibilityResponse | null;
  executiveSummary: ExecutiveSummary | null;
}): GlobalScoreResolution {
  const candidates = [
    {
      source: '/api/jobs/{job_id}/executive-summary accessibilityScore',
      value: executiveSummary?.accessibilityScore,
    },
    {
      source: '/api/jobs/{job_id}/executive-summary score',
      value: executiveSummary?.score,
    },
    {
      source: '/api/jobs/{job_id}/executive-summary summary.accessibilityScore',
      value: executiveSummary?.summary?.accessibilityScore,
    },
    {
      source: '/api/jobs/{job_id}/executive-summary summary.score',
      value: executiveSummary?.summary?.score,
    },
    {
      source: '/api/jobs/{job_id}/accessibility accessibilityScore',
      value: accessibility?.accessibilityScore,
    },
    {
      source: '/api/jobs/{job_id}/accessibility summary.accessibilityScore',
      value: accessibility?.summary.accessibilityScore,
    },
    {
      source:
        '/api/jobs/{job_id}/resources access.executiveSummary.accessibilityScore',
      value: access?.executiveSummary?.accessibilityScore,
    },
    {
      source: '/api/jobs/{job_id}/resources access.summary.accessibilityScore',
      value: access?.summary?.accessibilityScore,
    },
  ];

  for (const candidate of candidates) {
    const score = normalizeScore(candidate.value);

    if (score !== null) {
      return { value: score, source: candidate.source };
    }
  }

  return { value: null, source: null };
}

function normalizeBackendPriority(value: string | null | undefined) {
  const normalizedValue = normalizeComparableText(value);

  if (
    normalizedValue.includes('alta') ||
    normalizedValue.includes('high') ||
    normalizedValue.includes('critical') ||
    normalizedValue.includes('critica')
  ) {
    return 'high';
  }

  if (
    normalizedValue.includes('media') ||
    normalizedValue.includes('medium') ||
    normalizedValue.includes('warning')
  ) {
    return 'medium';
  }

  if (
    normalizedValue.includes('baja') ||
    normalizedValue.includes('low') ||
    normalizedValue.includes('ok')
  ) {
    return 'low';
  }

  if (
    normalizedValue.includes('not_scored') ||
    normalizedValue.includes('sin puntuacion')
  ) {
    return 'notAnalyzable';
  }

  return null;
}

function resolveBackendGlobalPriority({
  accessibility,
  executiveSummary,
}: {
  accessibility: AccessibilityResponse | null;
  executiveSummary: ExecutiveSummary | null;
}): GlobalPriorityResolution {
  const candidates = [
    {
      source: '/api/jobs/{job_id}/executive-summary priority',
      value: executiveSummary?.priority,
    },
    {
      source: '/api/jobs/{job_id}/executive-summary globalPriority',
      value: executiveSummary?.globalPriority,
    },
    {
      source: '/api/jobs/{job_id}/executive-summary summary.priority',
      value: executiveSummary?.summary?.priority,
    },
    {
      source: '/api/jobs/{job_id}/accessibility priority',
      value: accessibility?.priority,
    },
    {
      source: '/api/jobs/{job_id}/accessibility summary.priority',
      value: accessibility?.summary.priority,
    },
  ];

  for (const candidate of candidates) {
    const priority = normalizeBackendPriority(candidate.value);

    if (priority) {
      return {
        value: priority,
        rawValue: candidate.value ?? null,
        source: candidate.source,
      };
    }
  }

  return { value: null, rawValue: null, source: null };
}

function getScoreText(score: number | null) {
  return score === null ? 'Sin puntuación' : `${score}/100`;
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

function getPriority(
  score: number | null,
  accessibilityResult: AccessibilityResource | undefined,
): PriorityLevel {
  const backendPriority = normalizeComparableText(
    accessibilityResult?.priority,
  );

  if (
    backendPriority.includes('alta') ||
    backendPriority.includes('high') ||
    backendPriority.includes('critical') ||
    backendPriority.includes('critica')
  ) {
    return 'high';
  }

  if (
    backendPriority.includes('media') ||
    backendPriority.includes('medium') ||
    backendPriority.includes('warning')
  ) {
    return 'medium';
  }

  if (
    backendPriority.includes('baja') ||
    backendPriority.includes('low') ||
    backendPriority.includes('ok')
  ) {
    return 'low';
  }

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

function getPriorityFromBackendOrScore(
  rawPriority: string | null | undefined,
  score: number | null,
) {
  const backendPriority = normalizeBackendPriority(rawPriority);

  if (backendPriority) {
    return backendPriority;
  }

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
  if (priority === 'high') {
    return 'Prioridad alta';
  }

  if (priority === 'medium') {
    return 'Prioridad media';
  }

  if (priority === 'low') {
    return 'Prioridad baja';
  }

  return 'No analizable';
}

function getGlobalPriorityText(priority: PriorityLevel | null) {
  if (priority === 'high') {
    return 'Prioridad global: Alta';
  }

  if (priority === 'medium') {
    return 'Prioridad global: Media';
  }

  if (priority === 'low') {
    return 'Prioridad global: Baja';
  }

  if (priority === 'notAnalyzable') {
    return 'Prioridad global: Sin puntuación';
  }

  return 'Prioridad global: No disponible';
}

function getGlobalPriorityBadgeClasses(priority: PriorityLevel | null) {
  return priority
    ? getPriorityBadgeClasses(priority)
    : 'border-slate-200 bg-slate-50 text-slate-700';
}

function getPriorityBadgeClasses(priority: PriorityLevel) {
  if (priority === 'high') {
    return 'border-rose-200 bg-rose-50 text-danger';
  }

  if (priority === 'medium') {
    return 'border-amber-200 bg-amber-50 text-[#8a5a00]';
  }

  if (priority === 'low') {
    return 'border-emerald-200 bg-emerald-50 text-[#166534]';
  }

  return 'border-slate-200 bg-slate-50 text-slate-700';
}

function normalizeIssueText(value: string | null | undefined) {
  return (
    value
      ?.trim()
      .toLocaleLowerCase('es-ES')
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '') ?? ''
  );
}

function getNotebookIssueLabel(value: string) {
  const normalizedValue = normalizeIssueText(value);

  if (
    normalizedValue.includes('intro') ||
    normalizedValue.includes('explicacion inicial') ||
    normalizedValue.includes('context')
  ) {
    return 'Falta explicación inicial';
  }

  if (
    normalizedValue.includes('h1') ||
    normalizedValue.includes('titulo principal') ||
    normalizedValue.includes('main title')
  ) {
    return 'No hay título principal';
  }

  if (
    normalizedValue.includes('output') ||
    normalizedValue.includes('salida') ||
    normalizedValue.includes('visual') ||
    normalizedValue.includes('chart') ||
    normalizedValue.includes('graf')
  ) {
    return 'Outputs visuales sin explicación';
  }

  if (
    normalizedValue.includes('error') ||
    normalizedValue.includes('traceback') ||
    normalizedValue.includes('exception')
  ) {
    return 'Errores de ejecución guardados';
  }

  if (
    normalizedValue.includes('alt') ||
    normalizedValue.includes('imagen') ||
    normalizedValue.includes('image')
  ) {
    return 'Imágenes sin texto alternativo';
  }

  if (
    normalizedValue.includes('markdown') ||
    normalizedValue.includes('estructura') ||
    normalizedValue.includes('heading') ||
    normalizedValue.includes('titulo')
  ) {
    return 'Notebook sin estructura Markdown';
  }

  return value;
}

function getNoAccessReason(resource: ResourceListItem) {
  return (
    resource.reasonCode ||
    resource.accessNote ||
    resource.errorMessage ||
    resource.urlStatus ||
    resource.accessStatus
  );
}

function getPrimaryIssue(
  resource: ResourceListItem,
  accessibilityResult: AccessibilityResource | undefined,
  kind: AccessibilityResourceKind,
) {
  if (accessibilityResult?.mainIssue) {
    return kind === 'NOTEBOOK'
      ? getNotebookIssueLabel(accessibilityResult.mainIssue)
      : accessibilityResult.mainIssue;
  }

  const accessLabel = getAccessLabel(resource);

  if (
    accessLabel === 'REQUIERE SSO' ||
    accessLabel === 'REQUIERE INTERACCIÓN'
  ) {
    return 'No analizable automáticamente porque requiere acceso externo, SSO o interacción.';
  }

  if (accessLabel === 'NO ACCEDE') {
    return `No accede: ${getNoAccessReason(resource) ?? 'sin motivo informado'}.`;
  }

  const firstIssue = accessibilityResult?.checks.find(
    (check) =>
      check.status === 'FAIL' ||
      check.status === 'WARNING' ||
      check.status === 'ERROR',
  );

  if (firstIssue) {
    const issueText = firstIssue.title || firstIssue.id;
    return kind === 'NOTEBOOK' ? getNotebookIssueLabel(issueText) : issueText;
  }

  if (accessibilityResult?.error) {
    return accessibilityResult.error;
  }

  if (!accessibilityResult?.checks.length && kind === 'OTHER') {
    return 'Este tipo de recurso se analizará en una fase posterior.';
  }

  if (!accessibilityResult?.checks.length) {
    return 'Sin análisis automático disponible todavía.';
  }

  return 'Sin incidencias principales.';
}

function resourceHasFailure(
  accessibilityResult: AccessibilityResource | undefined,
) {
  const score = getResourceScore(accessibilityResult);
  return (
    accessibilityResult?.checks.some((check) => check.status === 'FAIL') ||
    accessibilityResult?.priority?.toLowerCase().includes('high') ||
    (score !== null && score < 60) ||
    false
  );
}

function resourceHasWarning(
  accessibilityResult: AccessibilityResource | undefined,
) {
  const score = getResourceScore(accessibilityResult);
  return (
    accessibilityResult?.checks.some((check) => check.status === 'WARNING') ||
    accessibilityResult?.priority?.toLowerCase().includes('medium') ||
    (score !== null && score >= 60 && score < 80) ||
    false
  );
}

function resourceMatchesFilters(
  resource: ResourceListItem,
  filters: ResourceFilters,
  accessibilityResult: AccessibilityResource | undefined,
) {
  if (filters.onlyNoAccess && !isNoAccessResource(resource)) {
    return false;
  }

  if (filters.onlyDownloadable && !resource.canDownload) {
    return false;
  }

  const selectedTypeFilters = [
    filters.onlyHtml,
    filters.onlyPdf,
    filters.onlyWord,
    filters.onlyVideo,
    filters.onlyNotebook,
  ].some(Boolean);

  if (selectedTypeFilters) {
    const kind = getResourceKind(resource, accessibilityResult);
    const matchesKind =
      (filters.onlyHtml && kind === 'HTML') ||
      (filters.onlyPdf && kind === 'PDF') ||
      (filters.onlyWord && kind === 'WORD') ||
      (filters.onlyVideo && kind === 'VIDEO') ||
      (filters.onlyNotebook && kind === 'NOTEBOOK');

    if (!matchesKind) {
      return false;
    }
  }

  if (filters.onlyFailures && !resourceHasFailure(accessibilityResult)) {
    return false;
  }

  if (filters.onlyWarnings && !resourceHasWarning(accessibilityResult)) {
    return false;
  }

  return true;
}

function filterGroups(
  groups: ResourceGroup[],
  filters: ResourceFilters,
  accessibilityByResourceId: Map<string, AccessibilityResource>,
) {
  return groups
    .map((group) => ({
      ...group,
      resources: group.resources.filter((resource) =>
        resourceMatchesFilters(
          resource,
          filters,
          accessibilityByResourceId.get(resource.id),
        ),
      ),
    }))
    .filter((group) => group.resources.length > 0);
}

function getExecutiveResourceKind(resource: ExecutiveResource) {
  return getKindFromValue(resource.type) ?? 'OTHER';
}

function executiveResourceHasFailure(resource: ExecutiveResource) {
  const score = normalizeScore(resource.score);
  const priority = normalizeBackendPriority(resource.priority);

  return priority === 'high' || (score !== null && score < 60);
}

function executiveResourceHasWarning(resource: ExecutiveResource) {
  const score = normalizeScore(resource.score);
  const priority = normalizeBackendPriority(resource.priority);

  return priority === 'medium' || (score !== null && score >= 60 && score < 80);
}

function executiveResourceMatchesFilters(
  resource: ExecutiveResource,
  filters: ResourceFilters,
) {
  if (
    filters.onlyNoAccess &&
    normalizeAccessLabel(resource.accessStatus) !== 'NO ACCEDE'
  ) {
    return false;
  }

  if (filters.onlyDownloadable && !resource.downloadable) {
    return false;
  }

  const selectedTypeFilters = [
    filters.onlyHtml,
    filters.onlyPdf,
    filters.onlyWord,
    filters.onlyVideo,
    filters.onlyNotebook,
  ].some(Boolean);

  if (selectedTypeFilters) {
    const kind = getExecutiveResourceKind(resource);
    const matchesKind =
      (filters.onlyHtml && kind === 'HTML') ||
      (filters.onlyPdf && kind === 'PDF') ||
      (filters.onlyWord && kind === 'WORD') ||
      (filters.onlyVideo && kind === 'VIDEO') ||
      (filters.onlyNotebook && kind === 'NOTEBOOK');

    if (!matchesKind) {
      return false;
    }
  }

  if (filters.onlyFailures && !executiveResourceHasFailure(resource)) {
    return false;
  }

  if (filters.onlyWarnings && !executiveResourceHasWarning(resource)) {
    return false;
  }

  return true;
}

function buildExecutiveGroups(
  modules: ExecutiveModule[],
): ExecutiveResourceGroup[] {
  return modules.map((module, index) => {
    const section = normalizeSectionName(module.title);

    return {
      id: `executive-${index}-${section}`,
      section,
      score: normalizeScore(module.score),
      priority: normalizeBackendPriority(module.priority),
      resourceCount: module.resourceCount || module.resources.length,
      analyzedCount: module.analyzedCount,
      resources: module.resources,
    };
  });
}

function filterExecutiveGroups(
  groups: ExecutiveResourceGroup[],
  filters: ResourceFilters,
) {
  return groups
    .map((group) => ({
      ...group,
      resources: group.resources.filter((resource) =>
        executiveResourceMatchesFilters(resource, filters),
      ),
    }))
    .filter((group) => group.resources.length > 0);
}

function Badge({
  children,
  className,
}: {
  children: string;
  className: string;
}) {
  return (
    <span className={classNames('badge whitespace-nowrap', className)}>
      {children}
    </span>
  );
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

function FilterCheckbox({
  checked,
  children,
  onChange,
}: {
  checked: boolean;
  children: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-3 rounded-2xl border border-line bg-white p-4 text-sm font-semibold text-ink">
      <input
        checked={checked}
        className="mt-1 h-5 w-5 accent-[var(--uoc-blue)]"
        onChange={(event) => onChange(event.target.checked)}
        type="checkbox"
      />
      <span>{children}</span>
    </label>
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
  const priority = getPriority(score, accessibilityResult);
  const resourceKind = getResourceKind(resource, accessibilityResult);
  const primaryIssue = getPrimaryIssue(
    resource,
    accessibilityResult,
    resourceKind,
  );

  return (
    <li className="rounded-2xl border border-line bg-white px-4 py-4">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <h4 className="break-words text-base font-semibold leading-6 text-ink">
            {resource.title}
          </h4>
          <p className="mt-1 text-sm text-subtle">
            Tipo: {getResourceTypeLabel(resourceKind)}
          </p>
          <p className="mt-2 text-sm leading-6 text-subtle">
            <span className="font-semibold text-ink">
              Incidencia principal:
            </span>{' '}
            {primaryIssue}
          </p>
        </div>

        <div className="flex shrink-0 flex-col gap-2 sm:flex-row sm:flex-wrap lg:justify-end">
          <ScoreBadge className="self-start sm:self-center" score={score} />
          <Badge className={getPriorityBadgeClasses(priority)}>
            {getPriorityLabel(priority)}
          </Badge>
        </div>
      </div>
    </li>
  );
}

function getExecutivePrimaryIssue(resource: ExecutiveResource) {
  const kind = getExecutiveResourceKind(resource);

  if (resource.mainIssue) {
    return kind === 'NOTEBOOK'
      ? getNotebookIssueLabel(resource.mainIssue)
      : resource.mainIssue;
  }

  const accessLabel = normalizeAccessLabel(resource.accessStatus);

  if (
    accessLabel === 'REQUIERE SSO' ||
    accessLabel === 'REQUIERE INTERACCIÓN'
  ) {
    return 'No analizable automáticamente porque requiere acceso externo, SSO o interacción.';
  }

  if (accessLabel === 'NO ACCEDE') {
    return 'No accede.';
  }

  if (normalizeScore(resource.score) === null) {
    return 'Sin análisis automático disponible todavía.';
  }

  return 'Sin incidencias principales.';
}

function ExecutiveResourceScoreRow({
  resource,
}: {
  resource: ExecutiveResource;
}) {
  const score = normalizeScore(resource.score);
  const priority = getPriorityFromBackendOrScore(resource.priority, score);
  const resourceKind = getExecutiveResourceKind(resource);
  const primaryIssue = getExecutivePrimaryIssue(resource);

  return (
    <li className="rounded-2xl border border-line bg-white px-4 py-4">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <h4 className="break-words text-base font-semibold leading-6 text-ink">
            {resource.title}
          </h4>
          <p className="mt-1 text-sm text-subtle">
            Tipo: {getResourceTypeLabel(resourceKind)}
          </p>
          <p className="mt-2 text-sm leading-6 text-subtle">
            <span className="font-semibold text-ink">
              Incidencia principal:
            </span>{' '}
            {primaryIssue}
          </p>
        </div>

        <div className="flex shrink-0 flex-col gap-2 sm:flex-row sm:flex-wrap lg:justify-end">
          <ScoreBadge className="self-start sm:self-center" score={score} />
          <Badge className={getPriorityBadgeClasses(priority)}>
            {getPriorityLabel(priority)}
          </Badge>
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
  const [access, setAccess] = useState<ResourceListResponse | null>(null);
  const [accessibility, setAccessibility] =
    useState<AccessibilityResponse | null>(null);
  const [executiveSummary, setExecutiveSummary] =
    useState<ExecutiveSummary | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [expandedPanels, setExpandedPanels] = useState<Record<string, boolean>>(
    {},
  );
  const [filters, setFilters] = useState<ResourceFilters>(EMPTY_FILTERS);
  const [isIssueInfoOpen, setIsIssueInfoOpen] = useState(false);
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

        setAccess(payload);
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

        try {
          const summaryPayload = await fetchExecutiveSummary(resolvedJobId);
          if (!cancelled) {
            setExecutiveSummary(summaryPayload);
          }
        } catch {
          if (!cancelled) {
            setExecutiveSummary(null);
          }
        }

        try {
          const jobPayload = await api.getJobStatus(resolvedJobId);
          if (!cancelled) {
            setJob(jobPayload);
          }
        } catch {
          if (!cancelled) {
            setJob(null);
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
  const filteredGroups = useMemo(
    () => filterGroups(groups, filters, accessibilityByResourceId),
    [accessibilityByResourceId, filters, groups],
  );
  const executiveGroups = useMemo(
    () => buildExecutiveGroups(executiveSummary?.modules ?? []),
    [executiveSummary],
  );
  const filteredExecutiveGroups = useMemo(
    () => filterExecutiveGroups(executiveGroups, filters),
    [executiveGroups, filters],
  );
  const shouldUseExecutiveGroups = executiveGroups.length > 0;
  const globalScore = useMemo(
    () =>
      resolveBackendGlobalScore({
        access,
        accessibility,
        executiveSummary,
      }),
    [access, accessibility, executiveSummary],
  );
  const globalPriority = useMemo(
    () =>
      resolveBackendGlobalPriority({
        accessibility,
        executiveSummary,
      }),
    [accessibility, executiveSummary],
  );
  const accessibilitySummary =
    accessibility?.summary ?? EMPTY_ACCESSIBILITY_SUMMARY;
  const accessibilitySummaryItems = [
    {
      label: getAnalyzedResourceLabel(
        accessibilitySummary.htmlResourcesAnalyzed,
        'HTML',
      ),
      value: accessibilitySummary.htmlResourcesAnalyzed,
    },
    {
      label: getAnalyzedResourceLabel(
        accessibilitySummary.pdfResourcesAnalyzed,
        'PDF',
      ),
      value: accessibilitySummary.pdfResourcesAnalyzed,
    },
    {
      label: getAnalyzedResourceLabel(
        accessibilitySummary.wordResourcesAnalyzed,
        'Word',
      ),
      value: accessibilitySummary.wordResourcesAnalyzed,
    },
    {
      label: getAnalyzedResourceLabel(
        accessibilitySummary.videoResourcesAnalyzed,
        'de vídeo',
      ),
      value: accessibilitySummary.videoResourcesAnalyzed,
    },
    {
      label: getAnalyzedResourceLabel(
        accessibilitySummary.notebookResourcesAnalyzed,
        'Notebook',
      ),
      value: accessibilitySummary.notebookResourcesAnalyzed,
    },
    { label: 'Incidencias', value: accessibilitySummary.fail },
    { label: 'Avisos', value: accessibilitySummary.warning },
  ];
  const activeFilterCount = Object.values(filters).filter(Boolean).length;
  const courseTitle = resolveCourseTitle({
    access,
    accessibility,
    executiveSummary,
    job,
  });

  useEffect(() => {
    if (!import.meta.env.DEV) {
      return;
    }

    console.debug('[AccessibleCourse] course title fields', {
      access: {
        courseName: access?.courseName,
        courseTitle: access?.courseTitle,
      },
      accessibility: {
        courseName: accessibility?.courseName,
        courseTitle: accessibility?.courseTitle,
      },
      executiveSummary: {
        courseName: executiveSummary?.courseName,
        courseTitle: executiveSummary?.courseTitle,
      },
      job: {
        courseName: job?.courseName,
        courseTitle: job?.courseTitle,
      },
      resolvedCourseTitle: courseTitle,
    });
  }, [access, accessibility, courseTitle, executiveSummary, job]);

  useEffect(() => {
    if (!import.meta.env.DEV) {
      return;
    }

    console.debug('[AccessibleCourse] executive global score fields', {
      endpointUsed: globalScore.source,
      endpointsConsumed: [
        '/api/jobs/{job_id}/executive-summary',
        '/api/jobs/{job_id}/accessibility',
        '/api/jobs/{job_id}/resources',
      ],
      globalPriorityFromBackend: globalPriority.rawValue,
      globalPrioritySource: globalPriority.source,
      globalScoreFromBackend: globalScore.value,
      displayedGlobalPriority: globalPriority.value,
      displayedGlobalScore: globalScore.value,
    });
  }, [globalPriority, globalScore]);

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
      showTokenButton={false}
      title="Análisis ejecutivo"
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
            <p className="mb-4 max-w-3xl text-lg leading-8 text-subtle">
              {courseTitle}
            </p>
            <p className="flex flex-col gap-3 text-xl font-semibold tracking-[-0.03em] text-ink sm:flex-row sm:items-center">
              <span>Score total</span>
              <span
                className={classNames(
                  'text-4xl font-semibold tracking-[-0.05em]',
                  getScoreTextClass(globalScore.value),
                )}
              >
                {getScoreText(globalScore.value)}
              </span>
              <span
                className={classNames(
                  'inline-flex w-fit rounded-full border px-3 py-1 text-sm font-semibold tracking-normal',
                  getGlobalPriorityBadgeClasses(globalPriority.value),
                )}
              >
                {getGlobalPriorityText(globalPriority.value)}
              </span>
            </p>
            {accessibilityError ? (
              <p className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-[#8a5a00]">
                No se pudo cargar la puntuación automática de accesibilidad:{' '}
                {accessibilityError}
              </p>
            ) : null}
          </section>

          <section className="rounded-3xl border border-line bg-white p-5 shadow-card">
            <h2 className="text-xl font-semibold tracking-[-0.03em] text-ink">
              Resumen de accesibilidad automática
            </h2>
            <dl className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {accessibilitySummaryItems.map((item) => (
                <div
                  className="rounded-2xl border border-line bg-[var(--color-surface-soft)] p-4"
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
            <div className="mt-4">
              <button
                aria-controls="issues-warnings-info"
                aria-expanded={isIssueInfoOpen}
                className="button-secondary w-full text-left sm:w-auto"
                onClick={() => setIsIssueInfoOpen((current) => !current)}
                type="button"
              >
                Más información sobre incidencias y avisos
              </button>
              <div
                className="mt-3 rounded-2xl border border-line bg-[var(--color-surface-soft)] p-4 text-sm leading-6 text-subtle"
                hidden={!isIssueInfoOpen}
                id="issues-warnings-info"
              >
                <p>
                  <span className="font-semibold text-ink">Incidencias:</span>{' '}
                  Son problemas detectados automáticamente que pueden impedir o
                  dificultar el acceso al contenido. Conviene revisarlos con
                  prioridad.
                </p>
                <p className="mt-2">
                  <span className="font-semibold text-ink">Avisos:</span> Son
                  posibles mejoras o elementos que requieren revisión manual. No
                  siempre implican una barrera directa, pero pueden afectar a la
                  calidad de la accesibilidad.
                </p>
              </div>
            </div>
          </section>

          <details className="rounded-3xl border border-line bg-white p-5 shadow-card">
            <summary className="cursor-pointer text-xl font-semibold tracking-[-0.03em] text-ink">
              Filtros
              {activeFilterCount > 0 ? ` (${activeFilterCount})` : ''}
            </summary>
            <div className="mt-5 space-y-4">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <FilterCheckbox
                  checked={filters.onlyNoAccess}
                  onChange={(checked) => updateFilter('onlyNoAccess', checked)}
                >
                  Mostrar solo NO ACCEDE
                </FilterCheckbox>
                <FilterCheckbox
                  checked={filters.onlyDownloadable}
                  onChange={(checked) =>
                    updateFilter('onlyDownloadable', checked)
                  }
                >
                  Mostrar solo descargables
                </FilterCheckbox>
                <FilterCheckbox
                  checked={filters.onlyFailures}
                  onChange={(checked) => updateFilter('onlyFailures', checked)}
                >
                  Mostrar solo incumplimientos
                </FilterCheckbox>
                <FilterCheckbox
                  checked={filters.onlyWarnings}
                  onChange={(checked) => updateFilter('onlyWarnings', checked)}
                >
                  Mostrar solo avisos
                </FilterCheckbox>
                <FilterCheckbox
                  checked={filters.onlyHtml}
                  onChange={(checked) => updateFilter('onlyHtml', checked)}
                >
                  Mostrar solo páginas web / HTML
                </FilterCheckbox>
                <FilterCheckbox
                  checked={filters.onlyPdf}
                  onChange={(checked) => updateFilter('onlyPdf', checked)}
                >
                  Mostrar solo recursos PDF
                </FilterCheckbox>
                <FilterCheckbox
                  checked={filters.onlyWord}
                  onChange={(checked) => updateFilter('onlyWord', checked)}
                >
                  Mostrar solo recursos Word
                </FilterCheckbox>
                <FilterCheckbox
                  checked={filters.onlyVideo}
                  onChange={(checked) => updateFilter('onlyVideo', checked)}
                >
                  Mostrar solo recursos de vídeo
                </FilterCheckbox>
                <FilterCheckbox
                  checked={filters.onlyNotebook}
                  onChange={(checked) => updateFilter('onlyNotebook', checked)}
                >
                  Mostrar solo recursos Notebook
                </FilterCheckbox>
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
          </details>

          <section className="space-y-4">
            <h2 className="text-xl font-semibold tracking-[-0.03em] text-ink">
              Recursos
            </h2>

            {shouldUseExecutiveGroups &&
            filteredExecutiveGroups.length === 0 ? (
              <div className="card-panel p-6 text-sm text-subtle">
                No hay recursos que coincidan con los filtros actuales.
              </div>
            ) : shouldUseExecutiveGroups ? (
              <div className="space-y-3">
                {filteredExecutiveGroups.map((group) => {
                  const panelId = toPanelId('section', group.id);
                  const isExpanded = expandedPanels[panelId] ?? false;

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
                            <ScoreBadge score={group.score} />
                            {group.priority ? (
                              <Badge
                                className={getPriorityBadgeClasses(
                                  group.priority,
                                )}
                              >
                                {getPriorityLabel(group.priority)}
                              </Badge>
                            ) : null}
                            <span className="text-sm font-medium text-subtle">
                              {isExpanded ? 'Cerrar' : 'Abrir'} ·{' '}
                              {formatResourceCount(group.resources.length)}
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
                            <ExecutiveResourceScoreRow
                              key={resource.resourceId}
                              resource={resource}
                            />
                          ))}
                        </ul>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : filteredGroups.length === 0 ? (
              <div className="card-panel p-6 text-sm text-subtle">
                No hay recursos que coincidan con los filtros actuales.
              </div>
            ) : (
              <div className="space-y-3">
                {filteredGroups.map((group) => {
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
                              {formatResourceCount(group.resources.length)}
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
                  navigate(`/report/${jobId}${getModeSearch(appMode)}`, {
                    state: { courseName: courseTitle },
                  })
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
