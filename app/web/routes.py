from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import SQLITE_PATH
from app.db.models import Row, Snapshot
from app.db.session import get_session
from app.export.export_csv import export_rows_csv
from app.export.export_jsonl import export_rows_jsonl
from app.trade2 import build_category_meta, get_category_rates, get_exchange_offers, get_trade_leagues, get_trade_static, read_history, read_latest_rates

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


def get_db():
    db = get_session()
    try:
        yield db
    finally:
        db.close()


@router.get("/", response_class=HTMLResponse)
def live_home(request: Request):
    return templates.TemplateResponse(request=request, name="live.html")


@router.get("/economy", response_class=HTMLResponse)
def economy_home(request: Request, db: Session = Depends(get_db)):
    leagues = sorted({snap.league for snap in db.scalars(select(Snapshot)).all()})
    categories = sorted({snap.category for snap in db.scalars(select(Snapshot)).all()})
    latest = db.scalars(select(Snapshot).order_by(Snapshot.created_at.desc())).first()
    return templates.TemplateResponse(
        request=request,
        name="economy.html",
        context={
            "leagues": leagues,
            "categories": categories,
            "default_snapshot": latest,
        },
    )


@router.get("/api/trade/leagues")
async def api_trade_leagues():
    try:
        return {"leagues": await get_trade_leagues()}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)


@router.get("/api/trade/static")
async def api_trade_static():
    try:
        categories = await get_trade_static()
        return {"categories": categories, "category_meta": build_category_meta(categories)}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)


@router.get("/api/trade/exchange")
async def api_trade_exchange(
    league: str = Query(...),
    have: str = Query(...),
    want: str = Query(...),
    status: str = Query("online", pattern="^(online|any)$"),
):
    try:
        return await get_exchange_offers(league=league, have=have, want=want, status=status)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)


@router.get("/api/trade/category-rates")
async def api_trade_category_rates(
    league: str = Query(...),
    category: str = Query(...),
    target: str = Query("divine"),
    status: str = Query("any", pattern="^(online|any)$"),
):
    try:
        return await get_category_rates(league=league, category=category, target=target, status=status)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)


@router.get("/api/trade/category-rates/latest")
def api_trade_category_rates_latest(
    league: str = Query(...),
    category: str = Query(...),
    target: str = Query("exalted"),
    status: str = Query("any", pattern="^(online|any)$"),
):
    latest = read_latest_rates(league=league, category=category, target=target, status=status)
    if not latest:
        return {"cached": False, "rows": []}
    return latest


@router.get("/api/trade/history")
def api_trade_history(limit: int = Query(30, ge=1, le=200)):
    return {"history": read_history(limit=limit)}


@router.get("/api/rows")
def api_rows(
    league: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    snapshot_id: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    stmt = select(Row, Snapshot).join(Snapshot, Row.snapshot_id == Snapshot.id)
    if league:
        stmt = stmt.where(Snapshot.league == league)
    if category:
        stmt = stmt.where(Snapshot.category == category)
    if snapshot_id:
        stmt = stmt.where(Row.snapshot_id == snapshot_id)
    rows = db.execute(stmt).all()
    payload = []
    columns_union = set()
    for row, snap in rows:
        cols = json.loads(row.columns_json)
        columns_union.update(cols.keys())
        payload.append(
            {
                "snapshot_id": row.snapshot_id,
                "row_id": row.row_id,
                "league": snap.league,
                "category": snap.category,
                "name": row.name,
                "icon_url": row.icon_url,
                "icon_local": row.icon_local,
                "columns": cols,
            }
        )
    if q:
        payload = [p for p in payload if q.lower() in p["name"].lower()]
    return {"columns": sorted(columns_union), "rows": payload}


@router.get("/row/{snapshot_id}/{row_id}", response_class=HTMLResponse)
def row_detail(snapshot_id: str, row_id: str, request: Request, db: Session = Depends(get_db)):
    stmt = select(Row).where(Row.snapshot_id == snapshot_id, Row.row_id == row_id)
    row = db.scalars(stmt).first()
    if not row:
        return PlainTextResponse("Not found", status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="row.html",
        context={
            "row": row,
            "columns": json.loads(row.columns_json),
            "raw": json.loads(row.raw_json),
        },
    )


@router.get("/export/csv")
def export_csv(
    league: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    snapshot_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    stmt = select(Row, Snapshot).join(Snapshot, Row.snapshot_id == Snapshot.id)
    if league:
        stmt = stmt.where(Snapshot.league == league)
    if category:
        stmt = stmt.where(Snapshot.category == category)
    if snapshot_id:
        stmt = stmt.where(Row.snapshot_id == snapshot_id)
    rows = db.execute(stmt).all()
    content = export_rows_csv(rows)
    return PlainTextResponse(content, media_type="text/csv")


@router.get("/export/jsonl")
def export_jsonl(
    league: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    snapshot_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    stmt = select(Row, Snapshot).join(Snapshot, Row.snapshot_id == Snapshot.id)
    if league:
        stmt = stmt.where(Snapshot.league == league)
    if category:
        stmt = stmt.where(Snapshot.category == category)
    if snapshot_id:
        stmt = stmt.where(Row.snapshot_id == snapshot_id)
    rows = db.execute(stmt).all()
    content = export_rows_jsonl(rows)
    return PlainTextResponse(content, media_type="application/jsonl")
