"""AlfaHRService — multi-user FastAPI application (API-only in production)."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.account import router as account_router
from app.api.admin import router as admin_router
from app.api.assistant import router as assistant_router
from app.api.auth import router as auth_router
from app.api.benchmark import router as benchmark_router
from app.api.search import router as search_router
from app.core.cleanup import periodic_cleanup, run_cleanup
from app.core.config import BASE_DIR, settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Init resources, run startup cleanup, launch periodic cleanup task."""
    from app.services.evaluation_service import init_semaphore
    init_semaphore(settings.llm_max_concurrent)

    await run_cleanup()

    cleanup_task = asyncio.create_task(periodic_cleanup())
    try:
        yield
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="AlfaHRService", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(account_router)
app.include_router(search_router)
app.include_router(benchmark_router)
app.include_router(assistant_router)


# --------------- Dev mode: serve frontend locally (production uses Nginx) ---------------

if not settings.is_production:
    _frontend_dir = BASE_DIR.parent / "frontend" / "pages"
    _static_dir = BASE_DIR.parent / "frontend" / "static"

    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

    @app.get("/favicon.ico")
    async def favicon():
        return FileResponse(_static_dir / "favicon.svg", media_type="image/svg+xml")

    @app.get("/{full_path:path}", response_class=HTMLResponse)
    async def serve_frontend(request: Request, full_path: str = ""):
        """Mimic Nginx try_files: $uri, $uri.html, /index.html."""
        if not full_path or full_path == "/":
            full_path = "index"

        # Try exact file
        candidate = _frontend_dir / full_path
        if candidate.is_file():
            return FileResponse(candidate)

        # Try with .html extension
        candidate_html = _frontend_dir / f"{full_path}.html"
        if candidate_html.is_file():
            return FileResponse(candidate_html)

        # Fallback to index.html
        return FileResponse(_frontend_dir / "index.html")


if __name__ == "__main__":
    from pathlib import Path

    import uvicorn

    _backend_dir = str(Path(__file__).resolve().parent.parent)
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        app_dir=_backend_dir,
    )
