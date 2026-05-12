from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import ICONS_DIR
from app.db.migrate import migrate
from app.web.routes import router

app = FastAPI(title="PoE2 Trade Helper")
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
app.mount("/icons", StaticFiles(directory=ICONS_DIR), name="icons")
templates = Jinja2Templates(directory="app/web/templates")


@app.on_event("startup")
def startup() -> None:
    migrate()


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.web.main:app", host="0.0.0.0", port=8000, reload=False)
