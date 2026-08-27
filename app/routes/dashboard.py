import logging
import datetime
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from pathlib import Path

from app.database import get_db
from app.auth import require_auth
from app.models import Book, Review, CheckRun, AppSetting
from app.amazon.marketplace import MARKETPLACES
from app.reviews.statistics import (
    get_dashboard_kpis,
    get_all_books_summary,
    get_top_performers,
    get_attention_books,
    get_book_statistics
)

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(dependencies=[Depends(require_auth)])

@router.get("/", response_class=HTMLResponse)
async def dashboard_home(
    request: Request,
    marketplace: Optional[str] = None,
    db: Session = Depends(get_db)
):
    from app.reviews.statistics import get_grouped_books_by_asin
    
    # Calculate marketplace counts & distribution
    mkt_stats = {}
    for domain, meta in MARKETPLACES.items():
        b_count = db.query(Book).filter(Book.marketplace == domain).count()
        r_count = db.query(Review).filter(Review.marketplace == domain).count()
        mkt_stats[domain] = {
            "domain": domain,
            "name": meta.get("name", domain),
            "flag": meta.get("flag", "🌐"),
            "country": meta.get("country", domain.split(".")[-1].lower()),
            "code": meta.get("code", domain.split(".")[-1].upper()),
            "book_count": b_count,
            "review_count": r_count
        }
        
    selected_marketplace = marketplace if marketplace and marketplace in mkt_stats else "amazon.it"
    grouped_summary = get_grouped_books_by_asin(db, selected_marketplace)
    
    # Distinct ASINs count across DB
    distinct_asins_count = db.query(func.count(func.distinct(Book.asin))).scalar() or 0
    
    # KPIs based on filtered view
    total_books_filtered = len(grouped_summary)
    total_reviews_filtered = sum(b["total_reviews"] for b in grouped_summary)
    if total_reviews_filtered > 0:
        total_rating_sum = sum(b["avg_rating"] * b["total_reviews"] for b in grouped_summary if b["total_reviews"] > 0)
        avg_rating_filtered = round(total_rating_sum / total_reviews_filtered, 2)
    else:
        avg_rating_filtered = 0.0
        
    new_30d_filtered = sum(b["reviews_30d"] for b in grouped_summary)
    
    kpis = {
        "total_books": total_books_filtered,
        "total_reviews": total_reviews_filtered,
        "avg_rating": avg_rating_filtered,
        "new_reviews_30d": new_30d_filtered
    }
    
    last_check_run = db.query(CheckRun).order_by(desc(CheckRun.checked_at)).first()
    last_check_setting = db.query(AppSetting).filter(AppSetting.key == "last_check_at").first()
    next_check_setting = db.query(AppSetting).filter(AppSetting.key == "next_check_at").first()
    freq_setting = db.query(AppSetting).filter(AppSetting.key == "check_frequency").first()
    
    last_update_str = "Nessun controllo effettuato"
    if last_check_run and last_check_run.checked_at:
        try:
            dt = last_check_run.checked_at
            last_update_str = dt.strftime("%d/%m/%Y alle %H:%M")
        except Exception:
            last_update_str = str(last_check_run.checked_at)[:16]
    elif last_check_setting and last_check_setting.value:
        try:
            dt = datetime.datetime.fromisoformat(last_check_setting.value)
            last_update_str = dt.strftime("%d/%m/%Y alle %H:%M")
        except Exception:
            last_update_str = last_check_setting.value[:16].replace("T", " ")

    next_update_str = "Non schedulato"
    if next_check_setting and next_check_setting.value:
        try:
            dt_next = datetime.datetime.fromisoformat(next_check_setting.value)
            next_update_str = dt_next.strftime("%d/%m/%Y alle %H:%M")
        except Exception:
            next_update_str = next_check_setting.value[:16].replace("T", " ")
    elif last_check_setting and last_check_setting.value:
        try:
            from app.reviews.monitor import parse_frequency_hours
            freq_hours = parse_frequency_hours(freq_setting.value if freq_setting else "24h")
            dt_last = datetime.datetime.fromisoformat(last_check_setting.value)
            dt_next = dt_last + datetime.timedelta(hours=freq_hours)
            next_update_str = dt_next.strftime("%d/%m/%Y alle %H:%M")
        except Exception:
            pass
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "kpis": kpis,
            "books_summary": grouped_summary,
            "all_books_count": distinct_asins_count,
            "mkt_stats": mkt_stats,
            "selected_marketplace": selected_marketplace,
            "last_check_run": last_check_run,
            "last_update_str": last_update_str,
            "next_update_str": next_update_str,
            "last_check_at": last_check_setting.value if last_check_setting else None,
            "next_check_at": next_check_setting.value if next_check_setting else None,
            "frequency": freq_setting.value if freq_setting else "24h",
            "active_tab": "dashboard"
        }
    )

@router.get("/book/{book_id}", response_class=HTMLResponse)
async def book_detail(book_id: int, request: Request, db: Session = Depends(get_db)):
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Libro non trovato")
        
    stats = get_book_statistics(db, book.id)
    reviews = db.query(Review).filter(Review.book_id == book.id).order_by(desc(Review.first_seen_at)).all()
    check_runs = db.query(CheckRun).filter(CheckRun.book_id == book.id).order_by(desc(CheckRun.checked_at)).limit(10).all()
    
    return templates.TemplateResponse(
        request=request,
        name="book_detail.html",
        context={
            "book": book,
            "stats": stats,
            "reviews": reviews,
            "check_runs": check_runs,
            "active_tab": "books"
        }
    )

@router.get("/reviews", response_class=HTMLResponse)
async def reviews_overview(
    request: Request,
    rating: Optional[float] = None,
    marketplace: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Review, Book).join(Book, Review.book_id == Book.id)
    
    if rating is not None:
        query = query.filter(Review.rating == rating)
    if marketplace:
        query = query.filter(Review.marketplace == marketplace)
        
    reviews_data = query.order_by(desc(Review.first_seen_at)).limit(100).all()
    marketplaces = [m[0] for m in db.query(Book.marketplace).distinct().all()]
    
    return templates.TemplateResponse(
        request=request,
        name="reviews.html",
        context={
            "reviews_data": reviews_data,
            "selected_rating": rating,
            "selected_marketplace": marketplace,
            "marketplaces": marketplaces,
            "active_tab": "reviews"
        }
    )
