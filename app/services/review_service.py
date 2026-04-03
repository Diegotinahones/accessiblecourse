from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func
from sqlmodel import Session, col, select

from app.core.config import Settings
from app.models.entities import (
    ChecklistItem,
    ChecklistResponse,
    ChecklistTemplate,
    ChecklistValue,
    Job,
    Resource,
    ResourceHealthStatus,
    ResourceType,
    ReviewSession,
    ReviewSessionStatus,
    ReviewState,
    ReviewSummary,
)


class InventoryResourceSeed(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    type: ResourceType
    origin: str | None = None
    url: str | None = None
    path: str | None = None
    course_path: str | None = Field(default=None, validation_alias=AliasChoices("course_path", "coursePath"))
    status: ResourceHealthStatus = ResourceHealthStatus.OK
    notes: str | list[str] | None = None

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | list[str] | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, list):
            cleaned = [item.strip() for item in value if item and item.strip()]
            return " | ".join(cleaned) if cleaned else None
        cleaned = value.strip()
        return cleaned or None


class ChecklistTemplateBundle(BaseModel):
    template: ChecklistTemplate
    items: list[ChecklistItem]

    model_config = ConfigDict(arbitrary_types_allowed=True)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _load_inventory_file(settings: Settings, job_id: str) -> list[InventoryResourceSeed]:
    inventory_path = Path(settings.data_dir) / "jobs" / job_id / "resources.json"
    if not inventory_path.exists():
        raise FileNotFoundError(f"No se ha encontrado inventario para el job '{job_id}' en {inventory_path}.")

    payload = json.loads(inventory_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("resources.json debe contener una lista de recursos.")
    return [InventoryResourceSeed.model_validate(item) for item in payload]


def ensure_job_inventory(session: Session, settings: Settings, job_id: str) -> None:
    count = session.exec(select(func.count()).select_from(Resource).where(Resource.job_id == job_id)).one()
    if count:
        ensure_review_rollups(session, job_id)
        return

    resources = _load_inventory_file(settings, job_id)
    job = session.get(Job, job_id)
    if job is None:
        job = Job(id=job_id, name=job_id.replace("-", " ").title())
        session.add(job)
        session.flush()

    for item in resources:
        session.add(
            Resource(
                id=item.id,
                job_id=job_id,
                title=item.title,
                type=item.type,
                origin=item.origin,
                url=item.url,
                path=item.path,
                course_path=item.course_path,
                status=item.status,
                notes=item.notes,
                review_state=ReviewState.IN_REVIEW,
            )
        )

    session.commit()
    ensure_review_rollups(session, job_id, touch=True)


def get_or_create_review_session(session: Session, job_id: str) -> ReviewSession:
    review_session = session.get(ReviewSession, job_id)
    if review_session is None:
        review_session = ReviewSession(job_id=job_id, status=ReviewSessionStatus.NOT_STARTED)
        session.add(review_session)
        session.flush()
    return review_session


def get_or_create_review_summary(session: Session, job_id: str) -> ReviewSummary:
    review_summary = session.get(ReviewSummary, job_id)
    if review_summary is None:
        review_summary = ReviewSummary(job_id=job_id, total_resources=0, total_fail_items=0)
        session.add(review_summary)
        session.flush()
    return review_summary


def ensure_review_rollups(session: Session, job_id: str, *, touch: bool = False) -> tuple[ReviewSession, ReviewSummary]:
    total_resources = session.exec(select(func.count()).select_from(Resource).where(Resource.job_id == job_id)).one()
    total_fail_items = session.exec(
        select(func.count())
        .select_from(ChecklistResponse)
        .where(ChecklistResponse.job_id == job_id, ChecklistResponse.value == ChecklistValue.FAIL)
    ).one()
    total_responses = session.exec(
        select(func.count()).select_from(ChecklistResponse).where(ChecklistResponse.job_id == job_id)
    ).one()
    ok_resources = session.exec(
        select(func.count())
        .select_from(Resource)
        .where(Resource.job_id == job_id, Resource.review_state == ReviewState.OK)
    ).one()

    now = _utc_now()
    summary = get_or_create_review_summary(session, job_id)
    summary.total_resources = int(total_resources)
    summary.total_fail_items = int(total_fail_items)
    if touch or summary.last_updated is None:
        summary.last_updated = now

    review_session = get_or_create_review_session(session, job_id)
    if total_responses == 0:
        review_session.status = ReviewSessionStatus.NOT_STARTED
    elif total_resources > 0 and ok_resources == total_resources and total_fail_items == 0:
        review_session.status = ReviewSessionStatus.COMPLETE
    else:
        review_session.status = ReviewSessionStatus.IN_PROGRESS

    if total_responses > 0 and review_session.started_at is None:
        review_session.started_at = now
    if touch or review_session.updated_at is None:
        review_session.updated_at = now

    session.commit()
    session.refresh(review_session)
    session.refresh(summary)
    return review_session, summary


def get_templates_by_type(session: Session) -> dict[ResourceType, ChecklistTemplateBundle]:
    templates = session.exec(select(ChecklistTemplate).order_by(ChecklistTemplate.resource_type)).all()
    items = session.exec(select(ChecklistItem).order_by(ChecklistItem.template_id, ChecklistItem.display_order)).all()
    items_by_template: dict[str, list[ChecklistItem]] = defaultdict(list)
    for item in items:
        items_by_template[item.template_id].append(item)
    return {
        template.resource_type: ChecklistTemplateBundle(template=template, items=items_by_template.get(template.id, []))
        for template in templates
    }


def get_template_bundle(session: Session, resource_type: ResourceType) -> ChecklistTemplateBundle:
    bundles = get_templates_by_type(session)
    bundle = bundles.get(resource_type) or bundles.get(ResourceType.OTHER)
    if bundle is None:
        raise LookupError("No hay plantillas de checklist disponibles.")
    return bundle


def get_resource_or_404(session: Session, job_id: str, resource_id: str) -> Resource:
    resource = session.get(Resource, resource_id)
    if resource is None or resource.job_id != job_id:
        raise LookupError(f"El recurso '{resource_id}' no existe.")
    return resource


def list_resources_with_fail_counts(session: Session, job_id: str) -> list[tuple[Resource, int]]:
    resources = session.exec(select(Resource).where(Resource.job_id == job_id).order_by(col(Resource.title))).all()
    fail_rows = session.exec(
        select(ChecklistResponse.resource_id, func.count(ChecklistResponse.id))
        .where(ChecklistResponse.job_id == job_id, ChecklistResponse.value == ChecklistValue.FAIL)
        .group_by(ChecklistResponse.resource_id)
    ).all()
    fail_count_by_resource = {resource_id: int(count) for resource_id, count in fail_rows}
    return [(resource, fail_count_by_resource.get(resource.id, 0)) for resource in resources]


def get_checklist_snapshot(
    session: Session, resource: Resource
) -> tuple[ChecklistTemplateBundle, dict[str, ChecklistResponse]]:
    template_bundle = get_template_bundle(session, resource.type)
    responses = session.exec(
        select(ChecklistResponse).where(
            ChecklistResponse.job_id == resource.job_id, ChecklistResponse.resource_id == resource.id
        )
    ).all()
    return template_bundle, {response.item_key: response for response in responses}


def upsert_checklist(
    session: Session,
    job_id: str,
    resource: Resource,
    incoming: list[dict[str, str | ChecklistValue | None]],
) -> tuple[ReviewState, int, datetime]:
    template_bundle, existing_responses = get_checklist_snapshot(session, resource)
    valid_keys = {item.key for item in template_bundle.items}
    seen_keys: set[str] = set()

    for item in incoming:
        item_key = str(item["itemKey"])
        if item_key in seen_keys:
            raise RuntimeError(f"El itemKey '{item_key}' aparece repetido en la petición.")
        if item_key not in valid_keys:
            raise RuntimeError(f"El itemKey '{item_key}' no pertenece al checklist del recurso.")
        seen_keys.add(item_key)

        response = existing_responses.get(item_key)
        if response is None:
            response = ChecklistResponse(job_id=job_id, resource_id=resource.id, item_key=item_key)
            session.add(response)
            existing_responses[item_key] = response

        response.value = ChecklistValue(item["value"])
        response.comment = str(item["comment"]).strip() if item.get("comment") else None
        response.updated_at = _utc_now()

    values_by_key = {item.key: ChecklistValue.PENDING for item in template_bundle.items}
    for item_key, response in existing_responses.items():
        values_by_key[item_key] = response.value

    fail_count = sum(value == ChecklistValue.FAIL for value in values_by_key.values())
    pass_count = sum(value == ChecklistValue.PASS for value in values_by_key.values())
    total_items = len(template_bundle.items)

    if fail_count > 0:
        resource.review_state = ReviewState.NEEDS_FIX
    elif total_items > 0 and pass_count == total_items:
        resource.review_state = ReviewState.OK
    else:
        resource.review_state = ReviewState.IN_REVIEW

    resource.updated_at = _utc_now()
    session.add(resource)
    session.commit()
    ensure_review_rollups(session, job_id, touch=True)
    session.refresh(resource)
    return resource.review_state, fail_count, resource.updated_at


def build_summary_payload(
    session: Session, job_id: str
) -> tuple[ReviewSession, ReviewSummary, list[dict[str, object]]]:
    review_session, summary = ensure_review_rollups(session, job_id)
    template_map = get_templates_by_type(session)
    fail_responses = session.exec(
        select(ChecklistResponse).where(
            ChecklistResponse.job_id == job_id, ChecklistResponse.value == ChecklistValue.FAIL
        )
    ).all()
    grouped_failures: dict[str, list[ChecklistResponse]] = defaultdict(list)
    for response in fail_responses:
        grouped_failures[response.resource_id].append(response)

    resources = session.exec(select(Resource).where(Resource.job_id == job_id).order_by(col(Resource.title))).all()
    rows: list[dict[str, object]] = []
    for resource in resources:
        failures = grouped_failures.get(resource.id, [])
        if not failures:
            continue
        template_bundle = template_map.get(resource.type) or template_map.get(ResourceType.OTHER)
        if template_bundle is None:
            raise LookupError("No hay plantillas de checklist disponibles.")
        template_items = {item.key: item for item in template_bundle.items}
        rows.append(
            {
                "resourceId": resource.id,
                "title": resource.title,
                "resourceType": resource.type,
                "reviewState": resource.review_state,
                "failCount": len(failures),
                "recommendations": [
                    {
                        "itemKey": response.item_key,
                        "label": template_items.get(response.item_key).label
                        if template_items.get(response.item_key)
                        else response.item_key,
                        "recommendation": template_items.get(response.item_key).recommendation
                        if template_items.get(response.item_key)
                        else None,
                        "comment": response.comment,
                    }
                    for response in failures
                ],
            }
        )
    return review_session, summary, rows
