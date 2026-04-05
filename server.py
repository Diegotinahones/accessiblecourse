from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse, JSONResponse

from app.main import app as api_app

app = api_app

# Frontend estático (Vite build -> public/)
PUBLIC_DIR = Path(__file__).parent / "public"
ASSETS_DIR = PUBLIC_DIR / "assets"

if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")


def _file_or_index(path: str) -> FileResponse:
    target = (PUBLIC_DIR / path).resolve()
    if target.is_file() and str(target).startswith(str(PUBLIC_DIR.resolve())):
        return FileResponse(target)
    return FileResponse(PUBLIC_DIR / "index.html")


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    return _file_or_index("index.html")


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    settings = getattr(app.state, "settings", None)
    version = getattr(settings, "version", "unknown")
    return {
        "status": "ok",
        "version": version,
        "time": datetime.now(tz=UTC).isoformat(),
    }


@app.get("/{path:path}", include_in_schema=False, response_model=None)
def spa(path: str) -> FileResponse | JSONResponse:
    if path.startswith("api/") or path == "api":
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    return _file_or_index(path)


@app.api_route(
    "/{path:path}",
    methods=["POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    include_in_schema=False,
    response_model=None,
)
def missing_non_get(path: str) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Not Found"})
