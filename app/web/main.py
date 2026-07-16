import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import ICONS_DIR, PUBLIC_CANONICAL_ORIGIN, PUBLIC_REDIRECT_HOSTS
from app.db.migrate import migrate
from app.market_service import market_snapshot_service
from app import wake_on_lan
from app.web.routes import router

STATIC_DIR = Path(__file__).resolve().parent / "static"
DISABLE_ALT_SVC_HEADER = "clear"
NO_PORT_API_PREFIXES = ("/api/",)
logger = logging.getLogger(__name__)


def canonical_public_redirect_url(request: Request) -> str | None:
    host = request.headers.get("host", "").lower()
    if not PUBLIC_CANONICAL_ORIGIN or host not in PUBLIC_REDIRECT_HOSTS:
        return None
    if request.url.path.startswith(NO_PORT_API_PREFIXES):
        return None
    query = request.url.query
    suffix = f"?{query}" if query else ""
    return f"{PUBLIC_CANONICAL_ORIGIN}{request.url.path}{suffix}"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    migrate()
    try:
        wake_result = await asyncio.to_thread(wake_on_lan.send_once_on_startup)
        logger.warning("Startup Wake-on-LAN result: %s", wake_result)
    except wake_on_lan.WakeOnLanError as exc:
        logger.warning("Startup Wake-on-LAN was not sent: %s", exc)
    await market_snapshot_service.start()
    try:
        yield
    finally:
        await market_snapshot_service.stop()


app = FastAPI(title="PoE2 Trade Helper", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[PUBLIC_CANONICAL_ORIGIN] if PUBLIC_CANONICAL_ORIGIN else [],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def redirect_public_host_to_canonical_port(request: Request, call_next):
    redirect_url = canonical_public_redirect_url(request)
    if redirect_url:
        response = RedirectResponse(url=redirect_url, status_code=308)
    else:
        response = await call_next(request)
    response.headers["Alt-Svc"] = DISABLE_ALT_SVC_HEADER
    return response


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/icons", StaticFiles(directory=ICONS_DIR), name="icons")


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(router)


if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run("app.web.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), reload=False)
