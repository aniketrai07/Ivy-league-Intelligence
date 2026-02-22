import asyncio
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from apscheduler.schedulers.background import BackgroundScheduler

from app.db import ExtractedData
from app.settings import config
from app.sources import SOURCES
from app.scraper import scrape_one


def run_pipeline(SessionLocal):
    async def _run():
        out = []
        for src in SOURCES:
            try:
                out.append(await scrape_one(src))
            except Exception as e:
                out.append({
                    "error": str(e),
                    "url": src["url"],
                    "university": src.get("university"),
                    "page_type": src.get("page_type")
                })
        return out

    results = asyncio.run(_run())

    db = SessionLocal()
    try:
        saved = 0
        skipped_duplicates = 0
        errors = 0

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
                skipped_duplicates += 1

        # cleanup (keep last N per uni)
        for uni in {s["university"] for s in SOURCES}:
            rows = (db.query(ExtractedData)
                    .filter(ExtractedData.university == uni)
                    .order_by(ExtractedData.extracted_at.desc())
                    .all())
            if len(rows) > config.MAX_PER_UNI_RECORDS:
                for old in rows[config.MAX_PER_UNI_RECORDS:]:
                    db.delete(old)
        db.commit()

        return {
            "saved_new_records": saved,
            "skipped_duplicates": skipped_duplicates,
            "errors": errors,
            "total_sources": len(SOURCES)
        }
    finally:
        db.close()


def start_scheduler(SessionLocal, minutes: int):
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: run_pipeline(SessionLocal),
                      "interval",
                      minutes=minutes,
                      id="ivy_scrape_job",
                      replace_existing=True)
    scheduler.start()
    return scheduler