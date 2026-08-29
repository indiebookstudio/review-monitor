import logging
import re
import json
from typing import Optional, List
from fastapi import APIRouter, Request, Depends, Form, HTTPException, status, Body
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pathlib import Path

from app.database import get_db
from app.auth import require_auth
from app.models import Book, Review, CheckRun, AuditLog
from app.amazon.marketplace import normalize_marketplace, get_product_url, MARKETPLACES
from app.amazon.client import AmazonClient
from app.reviews.monitor import run_book_check, reset_book_reviews, reset_asin_reviews
from app.reviews.statistics import get_all_books_summary

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/books", dependencies=[Depends(require_auth)])

def validate_asin(asin: str) -> str:
    cleaned = asin.strip()
    # If the user pasted a full URL, extract the ASIN from it
    url_match = re.search(r'/(?:dp|product|gp/product)/([A-Z0-9]{10})', cleaned, re.IGNORECASE)
    if url_match:
        return url_match.group(1).upper()
        
    # Remove any hyphens, spaces or slashes
    cleaned = re.sub(r'[\s\-_\/]', '', cleaned).upper()
    if re.match(r'^[A-Z0-9]{10}$', cleaned):
        return cleaned
    raise ValueError(f"Formato ASIN non valido: '{asin}'. Inserisci un codice ASIN di 10 caratteri (es. B0H7JK9R46) oppure incolla il link Amazon del libro.")

@router.get("", response_class=HTMLResponse)
async def list_books(request: Request, db: Session = Depends(get_db)):
    books_summary = get_all_books_summary(db)
    return templates.TemplateResponse(
        request=request,
        name="books.html",
        context={
            "books_summary": books_summary,
            "marketplaces": MARKETPLACES,
            "active_tab": "books",
            "msg": request.query_params.get("msg"),
            "error": request.query_params.get("error")
        }
    )

@router.post("/preview-asin")
async def preview_asin(request: Request, db: Session = Depends(get_db)):
    """
    Scans all 14 Amazon KDP stores for the provided ASIN, extracting cover image,
    title, paperback price, Kindle edition presence and price, and marketplace availability.
    Also checks if the ASIN already exists in the catalog.
    """
    try:
        data = await request.json()
    except Exception:
        data = {}
        
    raw_asin = data.get("asin") or request.query_params.get("asin", "")
    if not raw_asin:
        return JSONResponse({"success": False, "error": "ASIN non fornito"}, status_code=400)
        
    try:
        clean_asin = validate_asin(raw_asin)
    except ValueError as ve:
        return JSONResponse({"success": False, "error": str(ve)}, status_code=400)

    # Check if this ASIN already exists in DB
    existing_book = db.query(Book).filter(Book.asin == clean_asin).first()
    already_exists = existing_book is not None

    client = AmazonClient()
    scan_result = client.check_asin_across_all_marketplaces(clean_asin)
    scan_result["already_exists"] = already_exists
    scan_result["existing_title"] = existing_book.title if existing_book else None
    
    return JSONResponse({
        "success": True,
        "data": scan_result
    })

@router.get("/{book_id}/reviews-json")
async def get_book_reviews_json(book_id: int, db: Session = Depends(get_db)):
    """Returns all reviews for a book as JSON for the live review viewer modal, sorted with newest first."""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        return JSONResponse({"success": False, "error": "Libro non trovato"}, status_code=404)
        
    reviews = db.query(Review).filter(Review.book_id == book_id).all()
    
    # Sort reviews by review_date parsed (most recent first)
    def parse_review_sort_key(r):
        from app.reviews.statistics import format_compact_date
        d_str = format_compact_date(r.review_date)
        if d_str and d_str != "-":
            parts = d_str.split("/")
            if len(parts) == 3:
                try:
                    yr = int(parts[2])
                    full_yr = 2000 + yr if yr < 50 else 1900 + yr
                    return (full_yr, int(parts[1]), int(parts[0]))
                except ValueError:
                    pass
        if r.first_seen_at:
            return (r.first_seen_at.year, r.first_seen_at.month, r.first_seen_at.day)
        return (1970, 1, 1)

    reviews.sort(key=parse_review_sort_key, reverse=True)

    rev_list = []
    for r in reviews:
        parsed_images = []
        if r.images:
            try:
                parsed_images = json.loads(r.images)
            except Exception:
                parsed_images = [r.images] if r.images.startswith("http") else []

        rev_list.append({
            "id": r.id,
            "review_id": r.review_id,
            "rating": r.rating,
            "title": r.title or f"Valutazione {r.rating}★",
            "body": r.body or "",
            "author": r.author or "Cliente Amazon",
            "review_date": r.review_date or "",
            "review_url": r.review_url or book.product_url,
            "images": parsed_images,
            "video_url": r.video_url,
            "first_seen_at": r.first_seen_at.strftime("%d/%m/%Y %H:%M") if r.first_seen_at else ""
        })
        
    return JSONResponse({
        "success": True,
        "book": {
            "id": book.id,
            "title": book.title,
            "asin": book.asin,
            "marketplace": book.marketplace,
            "product_url": book.product_url,
            "cover_image_url": book.cover_image_url
        },
        "reviews": rev_list,
        "count": len(rev_list)
    })

@router.post("/add")
def add_book(
    request: Request,
    asin: str = Form(...),
    marketplace: str = Form(default="all"),
    title: Optional[str] = Form(default=None),
    cover_image_url: Optional[str] = Form(default=None),
    price: Optional[str] = Form(default=None),
    has_kindle: Optional[bool] = Form(default=False),
    kindle_price: Optional[str] = Form(default=None),
    selected_marketplaces: Optional[str] = Form(default=None),
    db: Session = Depends(get_db)
):
    try:
        clean_asin = validate_asin(asin)
        referer = request.headers.get("referer", "/")
        redirect_base = "/" if "books" not in referer else "/books"

        # Check if ASIN is already in catalog
        existing_any = db.query(Book).filter(Book.asin == clean_asin).first()
        if existing_any:
            return RedirectResponse(
                url=f"{redirect_base}?error=Il libro con ASIN '{clean_asin}' (\"{existing_any.title}\") è già presente nel tuo catalogo!",
                status_code=status.HTTP_303_SEE_OTHER
            )
        clean_title = title.strip() if title else ""
        clean_cover = cover_image_url.strip() if cover_image_url else None
        clean_price = price.strip() if price else None
        clean_kprice = kindle_price.strip() if kindle_price else None
        
        client = AmazonClient()
        
        # If title or cover is missing, do quick lookup
        if not clean_title or not clean_cover:
            preview = client.check_asin_across_all_marketplaces(clean_asin)
            if not clean_title and preview.get("title"):
                clean_title = preview["title"]
            if not clean_cover and preview.get("cover_image_url"):
                clean_cover = preview["cover_image_url"]
            if not clean_price and preview.get("price"):
                clean_price = preview["price"]
            if preview.get("has_kindle"):
                has_kindle = True
                if not clean_kprice:
                    clean_kprice = preview.get("kindle_price")

        clean_title = clean_title or f"Libro Amazon KDP ({clean_asin})"
        referer = request.headers.get("referer", "/")
        redirect_base = "/" if "books" not in referer else "/books"

        # Determine target marketplaces
        target_mkts = []
        if selected_marketplaces and selected_marketplaces != "all":
            target_mkts = [m.strip() for m in selected_marketplaces.split(",") if m.strip() in MARKETPLACES]
        elif marketplace == "all":
            target_mkts = list(MARKETPLACES.keys())
        else:
            target_mkts = [normalize_marketplace(marketplace)]

        if not target_mkts:
            target_mkts = list(MARKETPLACES.keys())

        added_books = []
        for mkt in target_mkts:
            existing = db.query(Book).filter(
                Book.asin == clean_asin,
                Book.marketplace == mkt
            ).first()
            if not existing:
                prod_url = get_product_url(clean_asin, mkt)
                b = Book(
                    asin=clean_asin,
                    marketplace=mkt,
                    title=clean_title,
                    product_url=prod_url,
                    cover_image_url=clean_cover,
                    price=clean_price,
                    has_kindle=bool(has_kindle),
                    kindle_price=clean_kprice,
                    enabled=True
                )
                db.add(b)
                added_books.append(b)

        audit = AuditLog(
            action="BOOK_ADDED",
            details=f"Aggiunto libro '{clean_title}' (ASIN: {clean_asin}) su {len(added_books)} marketplace."
        )
        db.add(audit)
        db.commit()

        # Immediately run bootstrap check for Italian/primary store
        for b in added_books:
            if b.marketplace == "amazon.it" or len(added_books) == 1:
                try:
                    run_book_check(b, db, client=client)
                except Exception as chk_err:
                    logger.warning(f"Immediate check warning for {b.asin}: {chk_err}")

        mkt_count_str = f"su tutti i {len(added_books)} marketplace" if len(added_books) > 1 else f"su {target_mkts[0]}"
        return RedirectResponse(
            url=f"{redirect_base}?msg=Libro '{clean_title}' aggiunto e sincronizzato con successo {mkt_count_str}!",
            status_code=status.HTTP_303_SEE_OTHER
        )
    except ValueError as ve:
        referer = request.headers.get("referer", "/")
        redirect_base = "/" if "books" not in referer else "/books"
        return RedirectResponse(
            url=f"{redirect_base}?error={str(ve)}",
            status_code=status.HTTP_303_SEE_OTHER
        )
    except Exception as e:
        logger.error(f"Error adding book: {e}")
        referer = request.headers.get("referer", "/")
        redirect_base = "/" if "books" not in referer else "/books"
        return RedirectResponse(
            url=f"{redirect_base}?error=Errore durante il salvataggio del libro: {str(e)}",
            status_code=status.HTTP_303_SEE_OTHER
        )

# ==========================================
# Real-Time Streaming Update Endpoints (SSE)
# ==========================================
@router.get("/stream-check/asin/{asin}")
async def stream_check_asin(asin: str, db: Session = Depends(get_db)):
    """Streams live check logs for a specific ASIN across all 14 marketplace stores."""
    clean_asin = validate_asin(asin)
    
    # Ensure all 14 marketplaces exist in DB for this ASIN
    existing = db.query(Book).filter(Book.asin == clean_asin).all()
    if existing:
        sample = existing[0]
        existing_mkts = {b.marketplace for b in existing}
        for mkt in MARKETPLACES.keys():
            if mkt not in existing_mkts:
                prod_url = get_product_url(clean_asin, mkt)
                new_b = Book(
                    asin=clean_asin,
                    marketplace=mkt,
                    title=sample.title,
                    product_url=prod_url,
                    cover_image_url=sample.cover_image_url,
                    price=sample.price,
                    has_kindle=sample.has_kindle,
                    kindle_price=sample.kindle_price,
                    kindle_asin=sample.kindle_asin,
                    enabled=True
                )
                db.add(new_b)
        db.commit()

    books = db.query(Book).filter(Book.asin == clean_asin, Book.enabled == True).all()

    def event_generator():
        client = AmazonClient()
        total_revs = 0
        total_emails = 0
        
        yield f"data: {json.dumps({'type': 'start', 'text': f'⚡ Avvio scansione ultra-rapida per ASIN {clean_asin} su {len(books)} store in parallelo...'})}\n\n"
        
        from app.database import SessionLocal
        from app.notifications.email import send_digest_review_alert
        import concurrent.futures

        def check_single_store(book_id):
            worker_db = SessionLocal()
            try:
                b = worker_db.query(Book).filter(Book.id == book_id).first()
                if not b:
                    return None
                mkt_meta = MARKETPLACES.get(b.marketplace, {})
                flag = mkt_meta.get("flag", "🌐")
                code = mkt_meta.get("code", b.marketplace)
                res = run_book_check(b, worker_db, client=client, force_alert=False, send_email_immediately=False)
                return {
                    "marketplace": b.marketplace,
                    "title": b.title,
                    "asin": b.asin,
                    "flag": flag,
                    "code": code,
                    "reviews_found": res.get("reviews_found", 0),
                    "new_reviews_list": res.get("new_reviews_list", []),
                    "error": None
                }
            except Exception as ex:
                return {
                    "marketplace": getattr(b, "marketplace", "Store") if 'b' in locals() and b else "Store",
                    "title": getattr(b, "title", "Libro") if 'b' in locals() and b else "Libro",
                    "asin": getattr(b, "asin", clean_asin) if 'b' in locals() and b else clean_asin,
                    "flag": "⚠️",
                    "code": "",
                    "reviews_found": 0,
                    "new_reviews_list": [],
                    "error": str(ex)
                }
            finally:
                worker_db.close()

        digest_groups = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            future_map = {executor.submit(check_single_store, b.id): b for b in books}
            completed_idx = 0
            for future in concurrent.futures.as_completed(future_map):
                completed_idx += 1
                res = future.result()
                if not res:
                    continue
                title = res.get("title", "Libro")
                short_title = title if len(title) <= 32 else (title[:30] + "...")
                if res.get("error"):
                    mkt_err = res.get("marketplace", "Store")
                    flag = res.get("flag", "🌐")
                    err_msg = res.get("error", "Errore")
                    yield f"data: {json.dumps({'type': 'log_error', 'text': f'[{completed_idx}/{len(books)}] 📖 \"{short_title}\" ➔ ⚠️ {flag} {mkt_err}: {err_msg}'})}\n\n"
                else:
                    found = res["reviews_found"]
                    flag = res["flag"]
                    mkt = res["marketplace"]
                    n_revs = res.get("new_reviews_list", [])
                    if n_revs:
                        digest_groups.append({
                            "title": title,
                            "marketplace": mkt,
                            "asin": res.get("asin", clean_asin),
                            "reviews": n_revs
                        })
                    total_revs += found
                    if len(n_revs) > 0:
                        yield f"data: {json.dumps({'type': 'log_success', 'text': f'[{completed_idx}/{len(books)}] 📖 \"{short_title}\" ➔ ✅ {flag} {mkt}: Trovate {found} recensioni (+{len(n_revs)} NUOVE)!'})}\n\n"
                    elif found > 0:
                        yield f"data: {json.dumps({'type': 'log_info', 'text': f'[{completed_idx}/{len(books)}] 📖 \"{short_title}\" ➔ ⚪ {flag} {mkt}: {found} recensioni (già note)'})}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'log_info', 'text': f'[{completed_idx}/{len(books)}] 📖 \"{short_title}\" ➔ ⚪ {flag} {mkt}: 0 recensioni'})}\n\n"

        # Send 1 single consolidated digest email if new reviews were discovered
        if digest_groups:
            if send_digest_review_alert(digest_groups, db=db):
                total_emails = 1

        email_msg = f" ✉️ Inviata 1 notifica email con le nuove recensioni rilevate!" if total_emails > 0 else ""
        yield f"data: {json.dumps({'type': 'done', 'text': f'🎉 Aggiornamento completato con successo! Totale recensioni: {total_revs}.{email_msg}'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.get("/stream-check/all")
async def stream_check_all(db: Session = Depends(get_db)):
    """Streams live check logs for all active books across the database in parallel."""
    books = db.query(Book).filter(Book.enabled == True).all()

    def event_generator():
        client = AmazonClient()
        total_revs = 0
        total_emails = 0
        
        yield f"data: {json.dumps({'type': 'start', 'text': f'⚡ Inizio aggiornamento globale parallelo per {len(books)} marketplace monitorati...'})}\n\n"
        
        from app.database import SessionLocal
        from app.notifications.email import send_digest_review_alert
        import concurrent.futures

        def check_single_store(book_id):
            worker_db = SessionLocal()
            try:
                b = worker_db.query(Book).filter(Book.id == book_id).first()
                if not b:
                    return None
                mkt_meta = MARKETPLACES.get(b.marketplace, {})
                flag = mkt_meta.get("flag", "🌐")
                code = mkt_meta.get("code", b.marketplace)
                res = run_book_check(b, worker_db, client=client, force_alert=False, send_email_immediately=False)
                return {
                    "marketplace": b.marketplace,
                    "title": b.title,
                    "asin": b.asin,
                    "flag": flag,
                    "code": code,
                    "reviews_found": res.get("reviews_found", 0),
                    "new_reviews_list": res.get("new_reviews_list", []),
                    "error": None
                }
            except Exception as ex:
                return {
                    "marketplace": getattr(b, "marketplace", "Store") if 'b' in locals() and b else "Store",
                    "title": getattr(b, "title", "Libro") if 'b' in locals() and b else "Libro",
                    "asin": getattr(b, "asin", "") if 'b' in locals() and b else "",
                    "flag": "⚠️",
                    "code": "",
                    "reviews_found": 0,
                    "new_reviews_list": [],
                    "error": str(ex)
                }
            finally:
                worker_db.close()

        digest_groups = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            future_map = {executor.submit(check_single_store, b.id): b for b in books}
            completed_idx = 0
            for future in concurrent.futures.as_completed(future_map):
                completed_idx += 1
                res = future.result()
                if not res:
                    continue
                title = res.get("title", "Libro")
                short_title = title if len(title) <= 32 else (title[:30] + "...")
                if res.get("error"):
                    mkt_err = res.get("marketplace", "Store")
                    flag = res.get("flag", "🌐")
                    err_msg = res.get("error", "Errore")
                    yield f"data: {json.dumps({'type': 'log_error', 'text': f'[{completed_idx}/{len(books)}] 📖 \"{short_title}\" ➔ ⚠️ {flag} {mkt_err}: {err_msg}'})}\n\n"
                else:
                    found = res["reviews_found"]
                    flag = res["flag"]
                    mkt = res["marketplace"]
                    n_revs = res.get("new_reviews_list", [])
                    if n_revs:
                        digest_groups.append({
                            "title": title,
                            "marketplace": mkt,
                            "asin": res.get("asin", ""),
                            "reviews": n_revs
                        })
                    total_revs += found
                    if len(n_revs) > 0:
                        yield f"data: {json.dumps({'type': 'log_success', 'text': f'[{completed_idx}/{len(books)}] 📖 \"{short_title}\" ➔ ✅ {flag} {mkt}: Trovate {found} recensioni (+{len(n_revs)} NUOVE)!'})}\n\n"
                    elif found > 0:
                        yield f"data: {json.dumps({'type': 'log_info', 'text': f'[{completed_idx}/{len(books)}] 📖 \"{short_title}\" ➔ ⚪ {flag} {mkt}: {found} recensioni (già note)'})}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'log_info', 'text': f'[{completed_idx}/{len(books)}] 📖 \"{short_title}\" ➔ ⚪ {flag} {mkt}: 0 recensioni'})}\n\n"

        # Send 1 single consolidated digest email for all new reviews found in the global run
        if digest_groups:
            if send_digest_review_alert(digest_groups, db=db):
                total_emails = 1

        email_msg = f" ✉️ Inviata 1 notifica email riassuntiva con tutte le nuove recensioni." if total_emails > 0 else ""
        yield f"data: {json.dumps({'type': 'done', 'text': f'🎉 Controllo globale completato in tempo record! {total_revs} recensioni totali.{email_msg}'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.get("/stream-check/book/{book_id}")
async def stream_check_single_book(book_id: int, db: Session = Depends(get_db)):
    """Streams live check logs for a single book."""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Libro non trovato")

    def event_generator():
        client = AmazonClient()
        mkt_meta = MARKETPLACES.get(book.marketplace, {})
        flag = mkt_meta.get("flag", "🌐")
        
        yield f"data: {json.dumps({'type': 'start', 'text': f'🚀 Inizio verifica per \"{book.title}\" su {flag} {book.marketplace}...'})}\n\n"
        
        try:
            res = run_book_check(book, db, client=client, force_alert=False)
            found = res.get('reviews_found', 0)
            email_sent = res.get('email_sent', False)
            
            if found > 0:
                yield f"data: {json.dumps({'type': 'log_success', 'text': f'✅ Rilevate {found} recensioni su {book.marketplace}!'})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'log_info', 'text': f'⚪ Nessuna recensione trovata su {book.marketplace}.'})}\n\n"
                
            email_msg = " ✉️ Notifica email inviata con successo!" if email_sent else ""
            yield f"data: {json.dumps({'type': 'done', 'text': f'🎉 Controllo completato! {found} recensioni registrate.{email_msg}'})}\n\n"
        except Exception as ex:
            yield f"data: {json.dumps({'type': 'log_error', 'text': f'⚠️ Errore: {str(ex)}'})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'text': 'Controllo terminato con errori.'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# ==========================================
# Review Reset & Force Check Endpoints
# ==========================================
@router.post("/{book_id}/reset-reviews")
async def reset_single_book_reviews(book_id: int, request: Request, db: Session = Depends(get_db)):
    """Resets all reviews for a specific book."""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Libro non trovato")
        
    deleted_count = reset_book_reviews(book_id, db)
    referer = request.headers.get("referer", "/")
    return RedirectResponse(
        url=f"{referer}?msg=Azzerate {deleted_count} recensioni per '{book.title}'. Ora puoi riscaricarle premendo 'Forza Aggiornamento'.",
        status_code=status.HTTP_303_SEE_OTHER
    )

@router.post("/asin/{asin}/reset-reviews")
async def reset_asin_all_stores_reviews(asin: str, request: Request, db: Session = Depends(get_db)):
    """Resets all reviews for an ASIN across all its stores."""
    clean_asin = validate_asin(asin)
    deleted_count = reset_asin_reviews(clean_asin, db)
    referer = request.headers.get("referer", "/")
    return RedirectResponse(
        url=f"{referer}?msg=Azzerate {deleted_count} recensioni per l'ASIN {clean_asin} su tutti i marketplace. Ora puoi riscaricarle premendo 'Forza Aggiornamento'.",
        status_code=status.HTTP_303_SEE_OTHER
    )

@router.post("/{book_id}/force-check")
async def force_check_single_book(book_id: int, request: Request, db: Session = Depends(get_db)):
    """Forces immediate scrape for a book and sends email alert at the end if new reviews are found."""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Libro non trovato")
        
    res = run_book_check(book, db, force_alert=False, send_email_immediately=False)
    rev_count = res.get("reviews_found", 0)
    n_revs = res.get("new_reviews_list", [])
    email_sent = False
    if n_revs:
        from app.notifications.email import send_digest_review_alert
        email_sent = send_digest_review_alert([{
            "title": book.title,
            "marketplace": book.marketplace,
            "asin": book.asin,
            "reviews": n_revs
        }], db=db)
    
    email_status = " Email di notifica inviata con successo!" if email_sent else ""
    referer = request.headers.get("referer", "/")
    return RedirectResponse(
        url=f"{referer}?msg=Aggiornamento forzato completato per '{book.title}': {rev_count} recensioni rilevate.{email_status}",
        status_code=status.HTTP_303_SEE_OTHER
    )

@router.post("/asin/{asin}/force-check")
async def force_check_asin_all_stores(asin: str, request: Request, db: Session = Depends(get_db)):
    """Forces immediate scrape for all marketplace entries of an ASIN and triggers 1 email alert at the end."""
    clean_asin = validate_asin(asin)
    books = db.query(Book).filter(Book.asin == clean_asin, Book.enabled == True).all()
    if not books:
        raise HTTPException(status_code=404, detail="Nessun libro attivo con questo ASIN")
        
    total_revs = 0
    client = AmazonClient()
    digest_groups = []
    for b in books:
        r = run_book_check(b, db, client=client, force_alert=False, send_email_immediately=False)
        total_revs += r.get("reviews_found", 0)
        n_revs = r.get("new_reviews_list", [])
        if n_revs:
            digest_groups.append({
                "title": b.title,
                "marketplace": b.marketplace,
                "asin": b.asin,
                "reviews": n_revs
            })
            
    email_sent = False
    if digest_groups:
        from app.notifications.email import send_digest_review_alert
        email_sent = send_digest_review_alert(digest_groups, db=db)
        
    email_status = " (Inviata 1 email riepilogativa con le nuove recensioni)" if email_sent else ""
    referer = request.headers.get("referer", "/")
    return RedirectResponse(
        url=f"{referer}?msg=Controllo completato per ASIN {clean_asin} su {len(books)} marketplace! Rilevate {total_revs} recensioni.{email_status}",
        status_code=status.HTTP_303_SEE_OTHER
    )

@router.post("/asin/{asin}/delete")
async def delete_asin_all_marketplaces(asin: str, request: Request, db: Session = Depends(get_db)):
    """Deletes all book records for this ASIN across all 14 marketplace stores."""
    clean_asin = validate_asin(asin)
    books = db.query(Book).filter(Book.asin == clean_asin).all()
    if not books:
        raise HTTPException(status_code=404, detail="Nessun libro trovato con questo ASIN")
        
    title = books[0].title
    count = len(books)
    for b in books:
        db.delete(b)
        
    audit = AuditLog(
        action="BOOK_DELETED_ALL_MKT",
        details=f"Eliminato libro '{title}' (ASIN: {clean_asin}) da tutti i {count} marketplace."
    )
    db.add(audit)
    db.commit()
    
    referer = request.headers.get("referer", "/")
    redirect_base = "/" if "books" not in referer else "/books"
    return RedirectResponse(
        url=f"{redirect_base}?msg=Libro '{title}' ({clean_asin}) eliminato con successo da tutti i {count} marketplace!",
        status_code=status.HTTP_303_SEE_OTHER
    )

@router.post("/{book_id}/edit")
async def edit_book(
    book_id: int,
    request: Request,
    title: str = Form(...),
    marketplace: str = Form(...),
    asin: str = Form(...),
    price: Optional[str] = Form(default=None),
    cover_image_url: Optional[str] = Form(default=None),
    db: Session = Depends(get_db)
):
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Libro non trovato")
        
    try:
        clean_asin = validate_asin(asin)
        clean_marketplace = normalize_marketplace(marketplace)
        clean_title = title.strip()
        
        if (clean_asin != book.asin or clean_marketplace != book.marketplace):
            existing = db.query(Book).filter(
                Book.asin == clean_asin,
                Book.marketplace == clean_marketplace,
                Book.id != book.id
            ).first()
            if existing:
                return RedirectResponse(
                    url=f"/books?error=Un altro libro ha già ASIN {clean_asin} su {clean_marketplace}.",
                    status_code=status.HTTP_303_SEE_OTHER
                )
                
        old_info = f"{book.title} ({book.asin} - {book.marketplace})"
        book.title = clean_title
        book.asin = clean_asin
        book.marketplace = clean_marketplace
        book.product_url = get_product_url(clean_asin, clean_marketplace)
        if price:
            book.price = price.strip()
        if cover_image_url:
            book.cover_image_url = cover_image_url.strip()
            
        audit = AuditLog(
            action="BOOK_UPDATED",
            details=f"Modificato libro da '{old_info}' a '{clean_title}' ({clean_asin} - {clean_marketplace})"
        )
        db.add(audit)
        db.commit()
        
        return RedirectResponse(
            url=f"/books?msg=Libro aggiornato con successo!",
            status_code=status.HTTP_303_SEE_OTHER
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/books?error={str(e)}",
            status_code=status.HTTP_303_SEE_OTHER
        )

@router.post("/{book_id}/toggle")
async def toggle_book_status(book_id: int, db: Session = Depends(get_db)):
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Libro non trovato")
        
    book.enabled = not book.enabled
    action = "BOOK_ENABLED" if book.enabled else "BOOK_DISABLED"
    audit = AuditLog(
        action=action,
        details=f"Monitoraggio {'attivato' if book.enabled else 'disattivato'} per '{book.title}' ({book.asin})"
    )
    db.add(audit)
    db.commit()
    
    state_str = "riattivato" if book.enabled else "disattivato"
    return RedirectResponse(
        url=f"/books?msg=Monitoraggio {state_str} per '{book.title}'",
        status_code=status.HTTP_303_SEE_OTHER
    )

@router.post("/{book_id}/delete")
async def delete_book(book_id: int, db: Session = Depends(get_db)):
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Libro non trovato")
        
    title = book.title
    asin = book.asin
    
    db.delete(book)
    audit = AuditLog(
        action="BOOK_DELETED",
        details=f"Eliminato definitivamente libro e storico per '{title}' (ASIN: {asin})"
    )
    db.add(audit)
    db.commit()
    
    return RedirectResponse(
        url=f"/books?msg=Libro '{title}' e relativo storico eliminati con successo.",
        status_code=status.HTTP_303_SEE_OTHER
    )
