import datetime
import json
import logging
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session

from app.models import Book, Review, CheckRun, AppSetting, AuditLog
from app.amazon.client import AmazonClient
from app.amazon.parser import parse_amazon_reviews, STATUS_OK, STATUS_NO_REVIEWS, STATUS_PAGE_UNAVAILABLE, STATUS_PARSER_ERROR
from app.notifications.email import send_review_alert, get_setting

logger = logging.getLogger(__name__)

FREQUENCY_HOURS_MAP = {
    "1h": 1,
    "1 hour": 1,
    "1 ora": 1,
    "6h": 6,
    "6 hours": 6,
    "6 ore": 6,
    "12h": 12,
    "12 hours": 12,
    "12 ore": 12,
    "24h": 24,
    "1 day": 24,
    "1 giorno": 24,
    "3d": 72,
    "3 days": 72,
    "3 giorni": 72,
    "7d": 168,
    "7 days": 168,
    "7 giorni": 168,
}

def parse_frequency_hours(freq_str: str) -> int:
    if not freq_str:
        return 24
    key = str(freq_str).lower().strip()
    return FREQUENCY_HOURS_MAP.get(key, 24)

def is_check_due(db: Session) -> bool:
    setting_freq = db.query(AppSetting).filter(AppSetting.key == "check_frequency").first()
    freq_hours = parse_frequency_hours(setting_freq.value if setting_freq else "24h")
    
    last_check_setting = db.query(AppSetting).filter(AppSetting.key == "last_check_at").first()
    if not last_check_setting or not last_check_setting.value:
        return True
        
    try:
        last_check_time = datetime.datetime.fromisoformat(last_check_setting.value)
        elapsed = datetime.datetime.now(datetime.timezone.utc) - last_check_time
        return elapsed >= datetime.timedelta(hours=freq_hours)
    except Exception:
        return True

def update_check_schedule_timestamps(db: Session):
    now = datetime.datetime.now(datetime.timezone.utc)
    setting_freq = db.query(AppSetting).filter(AppSetting.key == "check_frequency").first()
    freq_hours = parse_frequency_hours(setting_freq.value if setting_freq else "24h")
    next_check = now + datetime.timedelta(hours=freq_hours)
    
    # Save last_check_at
    s_last = db.query(AppSetting).filter(AppSetting.key == "last_check_at").first()
    if not s_last:
        s_last = AppSetting(key="last_check_at", value=now.isoformat())
        db.add(s_last)
    else:
        s_last.value = now.isoformat()
        
    # Save next_check_at
    s_next = db.query(AppSetting).filter(AppSetting.key == "next_check_at").first()
    if not s_next:
        s_next = AppSetting(key="next_check_at", value=next_check.isoformat())
        db.add(s_next)
    else:
        s_next.value = next_check.isoformat()
        
    db.commit()

def run_book_check(
    book: Book, 
    db: Session, 
    client: Optional[AmazonClient] = None,
    force_alert: bool = False,
    send_email_immediately: bool = False
) -> Dict[str, Any]:
    if client is None:
        client = AmazonClient()

    logger.info(f"Checking book: '{book.title}' (ASIN: {book.asin}, Marketplace: {book.marketplace})")
    
    html, http_status, http_err = client.fetch_reviews_page(book.asin, book.marketplace)
    
    if not html or http_status != 200:
        error_msg = http_err or f"HTTP status {http_status}"
        logger.error(f"Amazon page unavailable for {book.asin}: {error_msg}")
        check_run = CheckRun(
            book_id=book.id,
            asin=book.asin,
            marketplace=book.marketplace,
            checked_at=datetime.datetime.now(datetime.timezone.utc),
            success=False,
            reviews_found=0,
            new_reviews=0,
            status_code=STATUS_PAGE_UNAVAILABLE,
            error_message=error_msg
        )
        db.add(check_run)
        db.commit()
        return {
            "success": False,
            "status": STATUS_PAGE_UNAVAILABLE,
            "reviews_found": 0,
            "new_reviews": 0,
            "new_reviews_list": [],
            "book_title": book.title,
            "marketplace": book.marketplace,
            "asin": book.asin,
            "is_bootstrap": False,
            "email_sent": False,
            "error": error_msg
        }

    parsed = parse_amazon_reviews(html, asin=book.asin, marketplace=book.marketplace)
    status_code = parsed["status"]
    
    # Synchronize cover image, product title, price and Kindle info
    updated_fields = False
    if parsed.get("product_title") and (not book.title or book.title.startswith("Amazon KDP Book") or book.title.startswith("Libro Amazon")):
        book.title = parsed["product_title"]
        updated_fields = True
    if parsed.get("cover_image_url") and not book.cover_image_url:
        book.cover_image_url = parsed["cover_image_url"]
        updated_fields = True
    if parsed.get("price"):
        book.price = parsed["price"]
        updated_fields = True
    if parsed.get("has_kindle"):
        book.has_kindle = True
        if parsed.get("kindle_price") and parsed["kindle_price"] != "Kindle Unlimited":
            book.kindle_price = parsed["kindle_price"]
        if parsed.get("kindle_asin"):
            book.kindle_asin = parsed["kindle_asin"]
        updated_fields = True

    # Synchronize cover, title, price to all other marketplace entries for the same ASIN if missing
    siblings = db.query(Book).filter(Book.asin == book.asin, Book.id != book.id).all()
    for sib in siblings:
        if book.cover_image_url and (not sib.cover_image_url or sib.cover_image_url != book.cover_image_url):
            sib.cover_image_url = book.cover_image_url
        if book.title and (not sib.title or sib.title.startswith("Libro Amazon KDP")):
            sib.title = book.title
        if book.price and not sib.price:
            sib.price = book.price
        if book.kindle_price and not sib.kindle_price:
            sib.kindle_price = book.kindle_price
            
    if updated_fields:
        db.commit()
    
    if status_code == STATUS_PAGE_UNAVAILABLE or status_code == STATUS_PARSER_ERROR:
        error_msg = parsed.get("error") or "Parser failed or blocked"
        logger.error(f"Failed parsing reviews for {book.asin}: {error_msg}")
        check_run = CheckRun(
            book_id=book.id,
            asin=book.asin,
            marketplace=book.marketplace,
            checked_at=datetime.datetime.now(datetime.timezone.utc),
            success=False,
            reviews_found=0,
            new_reviews=0,
            status_code=status_code,
            error_message=error_msg
        )
        db.add(check_run)
        db.commit()
        return {
            "success": False,
            "status": status_code,
            "reviews_found": 0,
            "new_reviews": 0,
            "new_reviews_list": [],
            "book_title": book.title,
            "marketplace": book.marketplace,
            "asin": book.asin,
            "is_bootstrap": False,
            "email_sent": False,
            "error": error_msg
        }

    reviews_list = parsed["reviews"]
    reviews_found_count = len(reviews_list)
    logger.info(f"Parsed {reviews_found_count} reviews from Amazon for {book.asin}")

    # Check if this is the first run for this book (Bootstrap)
    existing_count = db.query(Review).filter(Review.book_id == book.id).count()
    is_bootstrap = (existing_count == 0)

    # Existing review IDs for this specific book and marketplace
    existing_review_ids = set(
        r[0] for r in db.query(Review.review_id).filter(
            Review.book_id == book.id,
            Review.marketplace == book.marketplace
        ).all()
    )

    new_reviews_objects: List[Dict[str, Any]] = []
    
    for r_data in reviews_list:
        r_id = r_data["review_id"]
        if r_id not in existing_review_ids:
            new_rev = Review(
                book_id=book.id,
                asin=book.asin,
                marketplace=book.marketplace,
                review_id=r_id,
                rating=r_data["rating"],
                title=r_data["title"],
                body=r_data["body"],
                author=r_data["author"],
                review_date=r_data["review_date"],
                review_url=r_data["review_url"],
                images=json.dumps(r_data.get("images", [])) if r_data.get("images") else None,
                video_url=r_data.get("video_url"),
                first_seen_at=datetime.datetime.now(datetime.timezone.utc)
            )
            db.add(new_rev)
            existing_review_ids.add(r_id)
            new_reviews_objects.append(r_data)

    new_count = len(new_reviews_objects)
    email_sent = False
    
    if force_alert and reviews_list:
        logger.info(f"Force alert requested for {book.asin}: Triggering alert with {len(reviews_list)} reviews...")
        total_in_db = db.query(Review).filter(Review.book_id == book.id).count()
        ratings_tuples = db.query(Review.rating).filter(Review.book_id == book.id).all()
        all_ratings = [r[0] for r in ratings_tuples if r[0] is not None]
        avg_rating = round(sum(all_ratings) / len(all_ratings), 1) if all_ratings else 5.0
        
        if send_email_immediately:
            email_sent = send_review_alert(
                book.title,
                book.marketplace,
                book.asin,
                reviews_list[:5],
                db,
                total_in_db or len(reviews_list),
                avg_rating
            )
        new_count_for_alert = len(reviews_list)
        new_reviews_objects = reviews_list[:5]
    else:
        new_count_for_alert = new_count
        if new_count_for_alert > 0:
            logger.info(f"Found {new_count_for_alert} new reviews for {book.asin} on {book.marketplace}! Triggering alert...")
            total_in_db = db.query(Review).filter(Review.book_id == book.id).count()
            ratings_tuples = db.query(Review.rating).filter(Review.book_id == book.id).all()
            all_ratings = [r[0] for r in ratings_tuples if r[0] is not None]
            avg_rating = round(sum(all_ratings) / len(all_ratings), 1) if all_ratings else 5.0
            
            if send_email_immediately:
                email_sent = send_review_alert(
                    book.title,
                    book.marketplace,
                    book.asin,
                    new_reviews_objects,
                    db,
                    total_in_db,
                    avg_rating
                )

    check_run = CheckRun(
        book_id=book.id,
        asin=book.asin,
        marketplace=book.marketplace,
        checked_at=datetime.datetime.now(datetime.timezone.utc),
        success=True,
        reviews_found=reviews_found_count,
        new_reviews=new_count_for_alert,
        status_code=STATUS_OK if reviews_found_count > 0 else STATUS_NO_REVIEWS,
        error_message=None
    )
    db.add(check_run)
    db.commit()

    return {
        "success": True,
        "status": STATUS_OK if reviews_found_count > 0 else STATUS_NO_REVIEWS,
        "reviews_found": reviews_found_count,
        "new_reviews": new_count_for_alert,
        "new_reviews_list": new_reviews_objects if new_count_for_alert > 0 else [],
        "book_title": book.title,
        "marketplace": book.marketplace,
        "asin": book.asin,
        "is_bootstrap": is_bootstrap,
        "email_sent": email_sent,
        "error": None
    }

def run_all_checks(db: Session, force: bool = False, client: Optional[AmazonClient] = None, force_alert: bool = False) -> Dict[str, Any]:
    if not force and not is_check_due(db):
        logger.info("Check is not due yet. Skipping run.")
        return {
            "executed": False,
            "reason": "Not due yet",
            "results": []
        }

    logger.info("Starting check run for all active books...")
    books = db.query(Book).filter(Book.enabled == True).all()
    results = []
    total_new = 0
    total_emails = 0
    digest_groups = []

    if client is None:
        client = AmazonClient()

    for book in books:
        res = run_book_check(book, db, client, force_alert=force_alert, send_email_immediately=False)
        results.append({
            "book_id": book.id,
            "title": book.title,
            "asin": book.asin,
            "marketplace": book.marketplace,
            "result": res
        })
        n_revs = res.get("new_reviews_list", [])
        if n_revs:
            digest_groups.append({
                "title": book.title,
                "marketplace": book.marketplace,
                "asin": book.asin,
                "reviews": n_revs
            })
        total_new += res.get("new_reviews", 0)

    # Send 1 single consolidated digest email if new reviews were found
    if digest_groups:
        from app.notifications.email import send_digest_review_alert
        if send_digest_review_alert(digest_groups, db=db):
            total_emails = 1

    update_check_schedule_timestamps(db)
    
    # Audit log
    audit = AuditLog(
        action="MONITOR_RUN",
        details=f"Eseguito controllo per {len(books)} libri. Nuove recensioni: {total_new}. Email inviate: {total_emails}."
    )
    db.add(audit)
    db.commit()

    logger.info(f"Check run completed. Checked {len(books)} books. New reviews: {total_new}. Emails: {total_emails}.")
    return {
        "executed": True,
        "books_checked": len(books),
        "total_new_reviews": total_new,
        "total_emails_sent": total_emails,
        "results": results
    }

def reset_book_reviews(book_id: int, db: Session) -> int:
    """Deletes all stored reviews and check runs for a single book."""
    count = db.query(Review).filter(Review.book_id == book_id).count()
    db.query(Review).filter(Review.book_id == book_id).delete(synchronize_session=False)
    db.query(CheckRun).filter(CheckRun.book_id == book_id).delete(synchronize_session=False)
    
    book = db.query(Book).filter(Book.id == book_id).first()
    title = book.title if book else f"ID {book_id}"
    
    audit = AuditLog(
        action="REVIEWS_RESET",
        details=f"Azzerate {count} recensioni per il libro '{title}' (ID: {book_id})"
    )
    db.add(audit)
    db.commit()
    return count

def reset_asin_reviews(asin: str, db: Session) -> int:
    """Deletes all stored reviews and check runs for a given ASIN across all marketplaces."""
    clean_asin = asin.strip().upper()
    count = db.query(Review).filter(Review.asin == clean_asin).count()
    db.query(Review).filter(Review.asin == clean_asin).delete(synchronize_session=False)
    db.query(CheckRun).filter(CheckRun.asin == clean_asin).delete(synchronize_session=False)
    
    audit = AuditLog(
        action="REVIEWS_RESET_ASIN",
        details=f"Azzerate {count} recensioni per l'ASIN '{clean_asin}' su tutti i marketplace"
    )
    db.add(audit)
    db.commit()
    return count

def reset_all_reviews(db: Session) -> int:
    """Deletes all stored reviews and check runs in the entire database."""
    count = db.query(Review).count()
    db.query(Review).delete(synchronize_session=False)
    db.query(CheckRun).delete(synchronize_session=False)
    
    audit = AuditLog(
        action="REVIEWS_RESET_ALL",
        details=f"Azzerate TUTTE le {count} recensioni nel database"
    )
    db.add(audit)
    db.commit()
    return count
