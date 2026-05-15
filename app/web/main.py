from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import ICONS_DIR
from app.db.migrate import migrate
from app.market_service import market_snapshot_service
from app.web.routes import router

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    migrate()
    await market_snapshot_service.start()
    try:
        yield
    finally:
        await market_snapshot_service.stop()


app = FastAPI(title="PoE2 Trade Helper", lifespan=lifespan)
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
