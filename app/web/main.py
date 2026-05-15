from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import ICONS_DIR
from app.db.migrate import migrate
from app.market_service import market_snapshot_service
from app.web.routes import router

app = FastAPI(title="PoE2 Trade Helper")
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
app.mount("/icons", StaticFiles(directory=ICONS_DIR), name="icons")
templates = Jinja2Templates(directory="app/web/templates")


@app.on_event("startup")
async def startup() -> None:
    migrate()
    await market_snapshot_service.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await market_snapshot_service.stop()


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.web.main:app", host="0.0.0.0", port=8000, reload=False)
