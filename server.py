from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from app.main import app as api_app

app = FastAPI()

# Backend en /api
app.mount("/api", api_app)

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

@app.get("/{path:path}", include_in_schema=False)
def spa(path: str) -> FileResponse:
    if path.startswith("api/") or path == "api":
        return FileResponse(PUBLIC_DIR / "index.html")
    return _file_or_index(path)
