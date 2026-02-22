import json
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.exc import IntegrityError

from app.db import ExtractedData, get_session_maker
from app.scheduler import run_pipeline
from app.settings import config
from app.sources import SOURCES
from app.scraper import scrape_one
import asyncio

from fastapi.templating import Jinja2Templates



app = FastAPI(title="Ivy League Intelligence Web App")
templates = Jinja2Templates(directory="app/templates")

SessionLocal = get_session_maker(config.DB_URL)

# If you face double-run during reload, you can comment scheduler during testing.
# scheduler = start_scheduler(SessionLocal, config.SCHEDULE_MINUTES)

LAST_RUN = {"time": None, "saved_new_records": 0, "errors": 0, "skipped_duplicates": 0}

@app.get("/ping")
def ping():
    return {"ok": True}

def _latest_per_uni(db):
    
    universities = sorted({s["university"] for s in SOURCES})
    meta = {}
    for uni in universities:
        latest = (db.query(ExtractedData)
                  .filter(ExtractedData.university == uni)
                  .order_by(ExtractedData.extracted_at.desc())
                  .first())
        last_updated = latest.extracted_at.isoformat(sep=" ", timespec="seconds") if latest else None

        counts = {}
        for t in ["fees", "admissions", "deadlines", "programs", "aid", "about"]:
            counts[t] = db.query(ExtractedData).filter(
                ExtractedData.university == uni,
                ExtractedData.page_type == t
            ).count()

        meta[uni] = {"last_updated": last_updated, "counts": counts}
    return meta


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    universities = sorted({s["university"] for s in SOURCES})
    db = SessionLocal()
    try:
        record_count = db.query(ExtractedData).count()
        meta = _latest_per_uni(db)
    finally:
        db.close()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "title": "Dashboard • Ivy League Intelligence",
            "universities": universities,
            "source_count": len(SOURCES),
            "record_count": record_count,
            "meta": meta,
            "schedule_minutes": config.SCHEDULE_MINUTES,
            "last_run": LAST_RUN
        }
    )


@app.get("/university/{name}", response_class=HTMLResponse)
def university_page(name: str, request: Request):
    db = SessionLocal()
    try:
        rows = (db.query(ExtractedData)
                .filter(ExtractedData.university == name)
                .order_by(ExtractedData.extracted_at.desc())
                .limit(80)
                .all())

        latest_by_type = {}
        history = []

        for r in rows:
            try:
                parsed = json.loads(r.data_json)
            except Exception:
                parsed = {"raw": r.data_json}

            item = {
                "page_type": r.page_type,
                "url": r.url,
                "extracted_at": r.extracted_at.isoformat(sep=" ", timespec="seconds"),
                "data": parsed
            }
            history.append(item)

            if r.page_type not in latest_by_type:
                latest_by_type[r.page_type] = item

        snapshot = {
            "fees": latest_by_type.get("fees"),
            "admissions": latest_by_type.get("admissions"),
            "deadlines": latest_by_type.get("deadlines"),
            "programs": latest_by_type.get("programs"),
            "aid": latest_by_type.get("aid"),
            "about": latest_by_type.get("about"),
        }

        return templates.TemplateResponse(
            "university.html",
            {
                "request": request,
                "title": f"{name} • Ivy League Intelligence",
                "university": name,
                "snapshot": snapshot,
                "history": history[:25]
            }
        )
    finally:
        db.close()


@app.get("/run-ui", response_class=HTMLResponse)
def run_ui(request: Request):
    return templates.TemplateResponse("run.html", {
        "request": request,
        "title": "Run Scraper • Ivy League Intelligence"
    })


@app.get("/run-json")
def run_json():
    result = run_pipeline(SessionLocal)
    LAST_RUN["time"] = datetime.utcnow().isoformat()
    LAST_RUN["saved_new_records"] = result.get("saved_new_records", 0)
    LAST_RUN["errors"] = result.get("errors", 0)
    LAST_RUN["skipped_duplicates"] = result.get("skipped_duplicates", 0)
    return JSONResponse({"message": "Scrape run completed", "result": result, "time": LAST_RUN["time"]})


@app.get("/run-university/{name}")
def run_university(name: str):
    uni_sources = [s for s in SOURCES if s["university"].lower() == name.lower()]

    async def _run():
        out = []
        for src in uni_sources:
            try:
                out.append(await scrape_one(src))
            except Exception as e:
                out.append({"error": str(e), "url": src["url"], "page_type": src["page_type"]})
        return out

    results = asyncio.run(_run())

    db = SessionLocal()
    try:
        saved = 0
        errors = 0
        skipped = 0

        for r in results:
            if "error" in r:
                errors += 1
                continue

            row = ExtractedData(
                university=r["university"],
                page_type=r["page_type"],
                url=r["url"],
                extracted_at=datetime.utcnow(),
                content_hash=r["hash"],
                data_json=r["data_json"]
            )
            db.add(row)
            try:
                db.commit()
                saved += 1
            except IntegrityError:
                db.rollback()
                skipped += 1

        return {"university": name, "saved_new_records": saved, "errors": errors, "skipped_duplicates": skipped}
    finally:
        db.close()


@app.get("/api/latest")
def api_latest(limit: int = 80):
    db = SessionLocal()
    try:
        rows = (db.query(ExtractedData)
                .order_by(ExtractedData.extracted_at.desc())
                .limit(limit)
                .all())
        return [
            {
                "university": r.university,
                "page_type": r.page_type,
                "url": r.url,
                "extracted_at": r.extracted_at.isoformat(),
                "data": json.loads(r.data_json)
            }
            for r in rows
        ]
    finally:
        db.close()