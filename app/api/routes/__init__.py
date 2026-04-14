from fastapi import APIRouter

from app.api.routes.checklists import router as checklists_router
from app.api.routes.health import router as health_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.online import router as online_router
from app.api.routes.reports import router as reports_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(checklists_router)
api_router.include_router(jobs_router)
api_router.include_router(online_router)
api_router.include_router(reports_router)
