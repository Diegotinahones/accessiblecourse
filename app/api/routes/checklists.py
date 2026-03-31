from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import get_session
from app.schemas import ChecklistTemplateRead, ChecklistTemplatesResponse
from app.services.review_service import get_templates_by_type

router = APIRouter(tags=["checklists"])


@router.get("/checklists/templates", response_model=ChecklistTemplatesResponse)
def get_checklist_templates(session: Session = Depends(get_session)) -> ChecklistTemplatesResponse:
    template_map = get_templates_by_type(session)
    return ChecklistTemplatesResponse(
        templates={
            resource_type: ChecklistTemplateRead(
                templateId=bundle.template.id,
                resourceType=resource_type,
                items=[
                    {
                        "itemKey": item.key,
                        "label": item.label,
                        "description": item.description,
                        "recommendation": item.recommendation,
                    }
                    for item in bundle.items
                ],
            )
            for resource_type, bundle in template_map.items()
        }
    )
