"""AlfaHRService — multi-user FastAPI application."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, select

from app.core.config import BASE_DIR
from app.core.database import async_session_factory
from app.models.session import Session as SessionModel

# --------------- Lifespan ---------------


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Clean up expired sessions on startup."""
    async with async_session_factory() as db:
        await db.execute(
            delete(SessionModel).where(SessionModel.expires_at < datetime.now(timezone.utc))
        )
        await db.commit()
    yield


# --------------- App ---------------

app = FastAPI(title="AlfaHRService", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/favicon.ico")
async def favicon():
    """Redirect favicon request to static file."""
    return RedirectResponse("/static/favicon.svg", status_code=302)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


# --------------- Include routers ---------------

from app.api.account import router as account_router  # noqa: E402
from app.api.admin import router as admin_router  # noqa: E402
from app.api.assistant import router as assistant_router  # noqa: E402
from app.api.auth import router as auth_router  # noqa: E402
from app.api.benchmark import router as benchmark_router  # noqa: E402
from app.api.search import router as search_router  # noqa: E402

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(account_router)
app.include_router(search_router)
app.include_router(benchmark_router)
app.include_router(assistant_router)


# --------------- Pages ---------------

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Show login form. If already authenticated, redirect to index."""
    token = request.cookies.get("session_token")
    if token:
        async with async_session_factory() as db:
            result = await db.execute(
                select(SessionModel).where(
                    SessionModel.token == token,
                    SessionModel.expires_at > datetime.now(timezone.utc),
                )
            )
            if result.scalar_one_or_none():
                return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Serve the main home page with service selection (auth check is done client-side via /api/auth/me)."""
    return templates.TemplateResponse("home.html", {"request": request})


@app.get("/sourcer", response_class=HTMLResponse)
async def sourcer_page(request: Request):
    """Serve the AlfaHRSourcer search page (auth check is done client-side via /api/auth/me)."""
    return templates.TemplateResponse("sourcer.html", {"request": request})


@app.get("/benchmark", response_class=HTMLResponse)
async def benchmark_page(request: Request):
    """Serve the AlfaHRBenchmark page (auth check is done client-side via /api/auth/me)."""
    from app.core.config import BENCHMARK_AREAS, BENCHMARK_EXPERIENCE_OPTIONS, BENCHMARK_PERIOD_OPTIONS
    return templates.TemplateResponse("benchmark.html", {
        "request": request,
        "period_options": BENCHMARK_PERIOD_OPTIONS,
        "experience_options": [
            {"value": k, "label": v or "Без фильтра"}
            for k, v in BENCHMARK_EXPERIENCE_OPTIONS.items()
        ],
        "area_options": [{"value": k, "label": v} for k, v in BENCHMARK_AREAS.items()],
    })


@app.get("/assistant", response_class=HTMLResponse)
async def assistant_page(request: Request):
    """Serve the AlfaHRAssistent chat page (auth check is done client-side via /api/auth/me)."""
    return templates.TemplateResponse("assistant.html", {"request": request})


@app.get("/account", response_class=HTMLResponse)
async def account_page_static(request: Request):
    """Serve the account page (data loaded client-side via /api/account/status)."""
    return templates.TemplateResponse("account.html", {"request": request})


@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(request: Request):
    """Serve the admin page (auth check is done client-side via /api/auth/me)."""
    return templates.TemplateResponse("admin_users.html", {"request": request})


# --------------- Run ---------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
