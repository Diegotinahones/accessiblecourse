from __future__ import annotations

from fastapi import APIRouter

from app.api.routes.checklists import router as checklists_router
from app.api.routes.jobs import router as jobs_router

api_router = APIRouter(prefix="/api")
api_router.include_router(checklists_router)
api_router.include_router(jobs_router)
