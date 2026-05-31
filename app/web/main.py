from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import ICONS_DIR
from app.db.migrate import migrate
from app.market_service import market_snapshot_service
from app.web.routes import router

STATIC_DIR = Path(__file__).resolve().parent / "static"
CANONICAL_PUBLIC_HOST = "xapct.ru"
CANONICAL_PUBLIC_PORT = 9038
CANONICAL_PUBLIC_ORIGIN = f"https://{CANONICAL_PUBLIC_HOST}:{CANONICAL_PUBLIC_PORT}"
REDIRECT_TO_CANONICAL_PORT_HOSTS = {CANONICAL_PUBLIC_HOST, f"{CANONICAL_PUBLIC_HOST}:443"}
DISABLE_ALT_SVC_HEADER = "clear"
NO_PORT_API_PREFIXES = ("/api/",)


def canonical_public_redirect_url(request: Request) -> str | None:
    host = request.headers.get("host", "").lower()
    if host not in REDIRECT_TO_CANONICAL_PORT_HOSTS:
        return None
    if request.url.path.startswith(NO_PORT_API_PREFIXES):
        return None
    query = request.url.query
    suffix = f"?{query}" if query else ""
    return f"{CANONICAL_PUBLIC_ORIGIN}{request.url.path}{suffix}"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    migrate()
    await market_snapshot_service.start()
    try:
        yield
    finally:
        await market_snapshot_service.stop()


app = FastAPI(title="PoE2 Trade Helper", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[CANONICAL_PUBLIC_ORIGIN],
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
