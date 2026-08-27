import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings, BASE_DIR
from app.database import engine, Base, SessionLocal
from app.auth import get_admin_password_hash
from app.routes import auth, dashboard, books, settings as settings_routes

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("kdp-dashboard")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Ensure DB tables exist
    logger.info("Initializing database tables...")
    Base.metadata.create_all(bind=engine)
    
    # Auto-migrate new Book columns for SQLite if they don't exist yet
    from sqlalchemy import text
    with engine.connect() as conn:
        try:
            res = conn.execute(text("PRAGMA table_info(books)"))
            existing_cols = {row[1] for row in res.fetchall()}
            if "cover_image_url" not in existing_cols:
                conn.execute(text("ALTER TABLE books ADD COLUMN cover_image_url VARCHAR(500)"))
            if "price" not in existing_cols:
                conn.execute(text("ALTER TABLE books ADD COLUMN price VARCHAR(50)"))
            if "has_kindle" not in existing_cols:
                conn.execute(text("ALTER TABLE books ADD COLUMN has_kindle BOOLEAN DEFAULT 0"))
            if "kindle_price" not in existing_cols:
                conn.execute(text("ALTER TABLE books ADD COLUMN kindle_price VARCHAR(50)"))
            if "kindle_asin" not in existing_cols:
                conn.execute(text("ALTER TABLE books ADD COLUMN kindle_asin VARCHAR(20)"))
            # Auto-migrate Review columns
            res_rev = conn.execute(text("PRAGMA table_info(reviews)"))
            existing_rev_cols = {row[1] for row in res_rev.fetchall()}
            if "images" not in existing_rev_cols:
                conn.execute(text("ALTER TABLE reviews ADD COLUMN images TEXT"))
            if "video_url" not in existing_rev_cols:
                conn.execute(text("ALTER TABLE reviews ADD COLUMN video_url TEXT"))

            # Fix reviews unique index to allow international reviews per marketplace
            conn.execute(text("DROP INDEX IF EXISTS ix_reviews_review_id"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_reviews_review_id ON reviews (review_id)"))
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uix_review_id_marketplace ON reviews (review_id, marketplace)"))

            # Cleanup any placeholder or invalid review IDs from DB & clean Kindle Unlimited string
            conn.execute(text("DELETE FROM reviews WHERE review_id LIKE '%ADPlaceholder%' OR review_id NOT LIKE 'R%'"))
            conn.execute(text("UPDATE books SET kindle_price = NULL WHERE kindle_price = 'Kindle Unlimited' OR kindle_price LIKE '%Unlimited%'"))
            conn.commit()
        except Exception as mig_err:
            logger.warning(f"DB Migration check: {mig_err}")
    
    # Initialize password hash in DB if needed & auto-expand existing books to 14 marketplaces
    db = SessionLocal()
    try:
        get_admin_password_hash(db)
        from app.models import Book
        from app.amazon.marketplace import MARKETPLACES, get_product_url
        distinct_asins = db.query(Book.asin).distinct().all()
        for (asin_val,) in distinct_asins:
            existing = db.query(Book).filter(Book.asin == asin_val).all()
            if existing:
                sample = existing[0]
                existing_mkts = {b.marketplace for b in existing}
                for mkt in MARKETPLACES.keys():
                    if mkt not in existing_mkts:
                        prod_url = get_product_url(asin_val, mkt)
                        db.add(Book(
                            asin=asin_val,
                            marketplace=mkt,
                            title=sample.title,
                            product_url=prod_url,
                            cover_image_url=sample.cover_image_url,
                            price=sample.price,
                            has_kindle=sample.has_kindle,
                            kindle_price=sample.kindle_price,
                            kindle_asin=sample.kindle_asin,
                            enabled=True
                        ))
        db.commit()
        logger.info("Database & 14 Marketplaces auto-expansion completed.")
    except Exception as exp_err:
        logger.warning(f"Marketplace expansion warning: {exp_err}")
    finally:
        db.close()
        
    yield
    # Shutdown
    logger.info("Shutting down KDP Performance Dashboard...")

app = FastAPI(
    title="KDP Performance Dashboard",
    description="Private Amazon Review & Book Performance Monitor",
    version="1.0.0",
    lifespan=lifespan
)

# Session Middleware for server-side signed authentication
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.APP_SECRET_KEY,
    session_cookie="kdp_session",
    max_age=86400 * 30, # 30 days
    same_site="lax",
    https_only=False # Set to True in HTTPS production if required
)

# Static Files
static_dir = BASE_DIR / "app" / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Include Routers
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(books.router)
app.include_router(settings_routes.router)

# Custom exception handler for 303 redirects from require_auth
@app.exception_handler(status.HTTP_303_SEE_OTHER)
async def redirect_handler(request: Request, exc):
    location = exc.headers.get("Location", "/login")
    return RedirectResponse(url=location, status_code=status.HTTP_303_SEE_OTHER)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
