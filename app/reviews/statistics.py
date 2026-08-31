import datetime
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.models import Book, Review, CheckRun

def get_utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

def to_naive_utc(dt: Optional[datetime.datetime]) -> Optional[datetime.datetime]:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt

def get_dashboard_kpis(db: Session) -> Dict[str, Any]:
    now = get_utc_now()
    d7 = now - datetime.timedelta(days=7)
    d30 = now - datetime.timedelta(days=30)
    d60 = now - datetime.timedelta(days=60)
    
    total_books = db.query(func.count(func.distinct(Book.asin))).filter(Book.enabled == True).scalar() or 0
    total_reviews = db.query(Review).count()
    
    # Average rating across all reviews
    avg_rating_res = db.query(func.avg(Review.rating)).scalar()
    avg_rating = round(float(avg_rating_res), 2) if avg_rating_res is not None else 0.0
    
    # New reviews in last 30 days
    new_reviews_30d = db.query(Review).filter(Review.first_seen_at >= d30).count()
    
    # Previous 30 days (from 60d to 30d ago) for comparison trend
    prev_reviews_30d = db.query(Review).filter(Review.first_seen_at >= d60, Review.first_seen_at < d30).count()
    
    if new_reviews_30d > prev_reviews_30d:
        trend = "growth" # ↗
    elif new_reviews_30d < prev_reviews_30d:
        trend = "decrease" # ↘
    else:
        trend = "stable" # →
        
    return {
        "total_books": total_books,
        "total_reviews": total_reviews,
        "avg_rating": avg_rating,
        "new_reviews_30d": new_reviews_30d,
        "trend": trend,
        "trend_symbol": "↗" if trend == "growth" else ("↘" if trend == "decrease" else "→")
    }

def format_compact_date(date_str: Optional[str]) -> str:
    if not date_str or date_str in ("N/A", "-", "None"):
        return "-"
    import re
    months = {
        # Italian
        "gennaio": "01", "febbraio": "02", "marzo": "03", "aprile": "04",
        "maggio": "05", "giugno": "06", "luglio": "07", "agosto": "08",
        "settembre": "09", "ottobre": "10", "novembre": "11", "dicembre": "12",
        # English
        "january": "01", "february": "02", "march": "03", "april": "04",
        "may": "05", "june": "06", "july": "07", "august": "08",
        "september": "09", "october": "10", "november": "11", "december": "12",
        "jan": "01", "feb": "02", "mar": "03", "apr": "04", "jun": "06", "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
        # Spanish
        "enero": "01", "febrero": "02", "mayo": "05", "junio": "06", "julio": "07", "diciembre": "12",
        # French
        "janvier": "01", "février": "02", "fevrier": "02", "mars": "03", "avril": "04", "mai": "05", "juin": "06", "juillet": "07", "août": "08", "aout": "08", "décembre": "12",
        # German
        "januar": "01", "februar": "02", "märz": "03", "maerz": "03", "juli": "07", "oktober": "10", "dezember": "12"
    }
    cleaned = date_str.lower().strip()
    # Matches: "12 luglio 2026", "12 de julio de 2026", "12 juillet 2026", "12. juli 2026"
    m_eu = re.search(r'(\d{1,2})\.?(?:\s+de)?\s+([a-zà-ÿ]+)\.?(?:\s+de)?\s+(\d{4})', cleaned)
    if m_eu:
        day, m_name, year = m_eu.groups()
        m_num = months.get(m_name.strip("."))
        if m_num:
            return f"{int(day):02d}/{m_num}/{year[-2:]}"
    # Matches: "July 12, 2026", "Jul 12 2026"
    m_en = re.search(r'([a-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})', cleaned)
    if m_en:
        m_name, day, year = m_en.groups()
        m_num = months.get(m_name.strip("."))
        if m_num:
            return f"{int(day):02d}/{m_num}/{year[-2:]}"
    m_iso = re.search(r'(\d{4})-(\d{2})-(\d{2})', cleaned)
    if m_iso:
        year, month, day = m_iso.groups()
        return f"{day}/{month}/{year[-2:]}"
    return date_str[:8]

def get_book_statistics(db: Session, book_id: int) -> Dict[str, Any]:
    now = get_utc_now()
    d7 = now - datetime.timedelta(days=7)
    d30 = now - datetime.timedelta(days=30)
    d90 = now - datetime.timedelta(days=90)
    
    reviews = db.query(Review).filter(Review.book_id == book_id).order_by(desc(Review.first_seen_at)).all()
    total_count = len(reviews)
    
    if total_count > 0:
        avg_rating = round(sum(r.rating for r in reviews) / total_count, 2)
    else:
        avg_rating = 0.0
        
    reviews_7d = sum(1 for r in reviews if r.first_seen_at and to_naive_utc(r.first_seen_at) >= d7)
    reviews_30d = sum(1 for r in reviews if r.first_seen_at and to_naive_utc(r.first_seen_at) >= d30)
    reviews_90d = sum(1 for r in reviews if r.first_seen_at and to_naive_utc(r.first_seen_at) >= d90)
    
    # Star distribution
    star_counts = {5: 0, 4: 0, 3: 0, 2: 0, 1: 0}
    for r in reviews:
        s = int(round(r.rating))
        s = max(1, min(5, s))
        star_counts[s] += 1
        
    star_distribution = []
    for star in [5, 4, 3, 2, 1]:
        cnt = star_counts[star]
        pct = round((cnt / total_count * 100), 1) if total_count > 0 else 0.0
        star_distribution.append({
            "stars": star,
            "stars_label": "★" * star + "☆" * (5 - star),
            "count": cnt,
            "percentage": pct
        })
        
    # Last review date
    last_review = reviews[0] if reviews else None
    
    # Timeline data for charts
    timeline = []
    sorted_by_date = sorted(reviews, key=lambda x: x.first_seen_at or datetime.datetime.min)
    cumulative = 0
    date_map = {}
    for r in sorted_by_date:
        if r.first_seen_at:
            d_str = r.first_seen_at.strftime("%Y-%m-%d")
            cumulative += 1
            date_map[d_str] = cumulative
            
    for d_str, cum_val in date_map.items():
        timeline.append({"date": d_str, "cumulative": cum_val})

    # Latest check status
    latest_check = db.query(CheckRun).filter(CheckRun.book_id == book_id).order_by(desc(CheckRun.checked_at)).first()
    book_obj = db.query(Book).filter(Book.id == book_id).first()
    if book_obj and not book_obj.enabled:
        status_indicator = "Inattivo"
    elif latest_check and not latest_check.success and latest_check.status_code == "PARSER_ERROR":
        status_indicator = "Errore"
    elif avg_rating > 0 and avg_rating < 3.0:
        status_indicator = "Attenzione"
    else:
        status_indicator = "Attivo"
            
    return {
        "total_reviews": total_count,
        "avg_rating": avg_rating,
        "reviews_7d": reviews_7d,
        "reviews_30d": reviews_30d,
        "reviews_90d": reviews_90d,
        "last_review": last_review,
        "last_review_date": format_compact_date(last_review.review_date) if last_review else "-",
        "star_distribution": star_distribution,
        "star_counts": star_counts,
        "timeline": timeline,
        "latest_check": latest_check,
        "status_indicator": status_indicator
    }

def get_all_books_summary(db: Session) -> List[Dict[str, Any]]:
    books = db.query(Book).order_by(func.lower(Book.title).asc()).all()
    summaries = []
    
    for book in books:
        stats = get_book_statistics(db, book.id)
        summaries.append({
            "book": book,
            "stats": stats
        })
        
    return summaries

def get_grouped_books_by_asin(db: Session, marketplace: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Groups books by unique ASIN across marketplaces so that each distinct book
    is counted and displayed with cover, price, kindle info and stats.
    """
    if marketplace and marketplace != "all":
        books = db.query(Book).filter(Book.marketplace == marketplace).order_by(func.lower(Book.title).asc()).all()
        summaries = []
        for book in books:
            stats = get_book_statistics(db, book.id)
            
            # Fallbacks for cover and title if missing on this specific marketplace entry
            cover = book.cover_image_url
            title = book.title
            if not cover or title.startswith("Libro Amazon KDP"):
                sibling = db.query(Book).filter(Book.asin == book.asin, Book.cover_image_url.isnot(None)).first()
                if sibling:
                    if not cover and sibling.cover_image_url:
                        cover = sibling.cover_image_url
                    if title.startswith("Libro Amazon KDP") and not sibling.title.startswith("Libro Amazon KDP"):
                        title = sibling.title
                        
            clean_kprice = book.kindle_price
            if clean_kprice and ("unlimited" in clean_kprice.lower() or "0,00" in clean_kprice or "0.00" in clean_kprice):
                clean_kprice = None
                
            summaries.append({
                "asin": book.asin,
                "title": title,
                "cover_image_url": cover,
                "price": book.price,
                "has_kindle": book.has_kindle and clean_kprice is not None,
                "kindle_price": clean_kprice,
                "kindle_asin": book.kindle_asin,
                "primary_book": book,
                "marketplaces": [{
                    "domain": book.marketplace,
                    "url": book.product_url,
                    "id": book.id,
                    "enabled": book.enabled,
                    "reviews_count": stats["total_reviews"],
                    "avg_rating": stats["avg_rating"],
                    "price": book.price,
                    "has_kindle": book.has_kindle,
                    "kindle_price": clean_kprice
                }],
                "total_reviews": stats["total_reviews"],
                "avg_rating": stats["avg_rating"],
                "reviews_7d": stats["reviews_7d"],
                "reviews_30d": stats["reviews_30d"],
                "last_review_date": stats["last_review_date"],
                "status_indicator": stats["status_indicator"],
                "enabled": book.enabled,
                "created_at": book.created_at
            })
        return summaries

def format_marketplace_price(price_str: Optional[str], marketplace: str) -> Optional[str]:
    if not price_str:
        return None

    from app.amazon.marketplace import MARKETPLACES
    meta = MARKETPLACES.get(marketplace, {})
    expected_symbol = meta.get("symbol", "€")
    code = meta.get("code", "IT")

    clean_str = price_str.replace("\xa0", " ").strip()
    
    # If the price string already carries the target market's currency symbol or code
    if expected_symbol == "$" and ("$" in clean_str or "USD" in clean_str) and not "CA$" in clean_str and not "AU$" in clean_str:
        return clean_str
    if expected_symbol == "£" and ("£" in clean_str or "GBP" in clean_str):
        return clean_str
    if expected_symbol == "CA$" and ("CA$" in clean_str or "CAD" in clean_str):
        return clean_str
    if expected_symbol == "AU$" and ("AU$" in clean_str or "AUD" in clean_str):
        return clean_str
    if expected_symbol == "¥" and ("¥" in clean_str or "JPY" in clean_str):
        return clean_str
    if expected_symbol == "zł" and ("zł" in clean_str or "PLN" in clean_str):
        return clean_str
    if expected_symbol == "kr" and ("kr" in clean_str or "SEK" in clean_str):
        return clean_str
    if expected_symbol == "€" and ("€" in clean_str or "EUR" in clean_str):
        return clean_str

    # Extract raw numeric value
    import re
    num_match = re.search(r'([\d.,]+)', clean_str)
    if not num_match:
        return clean_str

    raw_num_str = num_match.group(1)
    if "," in raw_num_str and "." in raw_num_str:
        if raw_num_str.rfind(",") > raw_num_str.rfind("."):
            raw_num_str = raw_num_str.replace(".", "").replace(",", ".")
        else:
            raw_num_str = raw_num_str.replace(",", "")
    elif "," in raw_num_str:
        raw_num_str = raw_num_str.replace(",", ".")

    try:
        val = float(raw_num_str)
    except ValueError:
        return clean_str

    if code == "US":
        return f"${val * 1.08:.2f}"
    elif code == "UK":
        return f"£{val * 0.86:.2f}"
    elif code == "CA":
        return f"CA${val * 1.50:.2f}"
    elif code == "AU":
        return f"AU${val * 1.65:.2f}"
    elif code == "PL":
        return f"{val * 4.30:.2f} zł".replace(".", ",")
    elif code == "SE":
        return f"{val * 11.40:.2f} kr".replace(".", ",")
    elif code == "JP":
        return f"¥{int(round(val * 165)):,}"
    else:
        return f"{val:.2f} €".replace(".", ",")

def get_grouped_books_by_asin(db: Session, selected_marketplace: Optional[str] = "amazon.it") -> List[Dict[str, Any]]:
    """
    Groups books by ASIN across all marketplaces.
    """
    query = db.query(Book)
    all_books = query.all()
    
    grouped: Dict[str, List[Book]] = {}
    for b in all_books:
        grouped.setdefault(b.asin, []).append(b)
        
    summaries = []
    display_mkt = selected_marketplace if (selected_marketplace and selected_marketplace != "all") else "amazon.it"

    for asin, b_list in grouped.items():
        primary = next((b for b in b_list if b.marketplace == "amazon.it"), b_list[0])
        best_title = primary.title
        best_cover = primary.cover_image_url
        has_kindle = primary.has_kindle
        kindle_price = primary.kindle_price

        # If a specific marketplace is selected, prioritize its specific price
        target_mkt_book = None
        if selected_marketplace and selected_marketplace != "all":
            target_mkt_book = next((b for b in b_list if b.marketplace == selected_marketplace), None)

        # Determine best price: prioritize current marketplace's local price, then primary, then any sibling
        if target_mkt_book and target_mkt_book.price:
            best_price = target_mkt_book.price
        elif primary and primary.price:
            best_price = primary.price
        else:
            best_price = next((b.price for b in b_list if b.price), None)

        if target_mkt_book and target_mkt_book.kindle_price:
            kindle_price = target_mkt_book.kindle_price
        elif not kindle_price:
            kindle_price = next((b.kindle_price for b in b_list if b.kindle_price), None)

        # Format price strictly in the currency of the selected marketplace
        best_price = format_marketplace_price(best_price, display_mkt)
        kindle_price = format_marketplace_price(kindle_price, display_mkt)

        for b in b_list:
            if b.title and not b.title.startswith("Amazon KDP Book") and not b.title.startswith("Libro Amazon"):
                best_title = b.title
            if b.cover_image_url and not best_cover:
                best_cover = b.cover_image_url
            if b.has_kindle:
                has_kindle = True

        mkt_entries = []
        for b in b_list:
            st = get_book_statistics(db, b.id)
            mkt_entries.append({
                "domain": b.marketplace,
                "url": b.product_url,
                "id": b.id,
                "enabled": b.enabled,
                "reviews_count": st["total_reviews"],
                "avg_rating": st["avg_rating"],
                "price": format_marketplace_price(b.price, b.marketplace),
                "has_kindle": b.has_kindle,
                "kindle_price": format_marketplace_price(b.kindle_price, b.marketplace)
            })

        # Calculate metrics strictly for the selected marketplace tab
        if selected_marketplace and selected_marketplace != "all":
            if target_mkt_book:
                st = get_book_statistics(db, target_mkt_book.id)
                total_revs = st["total_reviews"]
                avg_rating = st["avg_rating"]
                tot_7d = st["reviews_7d"]
                tot_30d = st["reviews_30d"]
                last_date = st["last_review_date"]
                status_ind = "Attivo" if target_mkt_book.enabled else "Inattivo"
                is_enabled = target_mkt_book.enabled
            else:
                total_revs = 0
                avg_rating = 0.0
                tot_7d = 0
                tot_30d = 0
                last_date = "-"
                status_ind = "Inattivo"
                is_enabled = False
        else:
            total_revs = 0
            total_rating_weighted = 0.0
            tot_7d = 0
            tot_30d = 0
            last_date = "-"
            for b in b_list:
                st = get_book_statistics(db, b.id)
                total_revs += st["total_reviews"]
                if st["total_reviews"] > 0:
                    total_rating_weighted += st["avg_rating"] * st["total_reviews"]
                tot_7d += st["reviews_7d"]
                tot_30d += st["reviews_30d"]
                if st["last_review_date"] != "-":
                    last_date = st["last_review_date"]
            avg_rating = round(total_rating_weighted / total_revs, 2) if total_revs > 0 else 0.0
            is_enabled = any(b.enabled for b in b_list)
            status_ind = "Attivo" if is_enabled else "Inattivo"

        # Determine the current product URL and book record for the selected marketplace
        current_book = target_mkt_book or primary
        current_product_url = current_book.product_url if (current_book and current_book.product_url) else get_product_url(asin, display_mkt)

        summaries.append({
            "asin": asin,
            "title": best_title,
            "cover_image_url": best_cover,
            "price": best_price,
            "product_url": current_product_url,
            "has_kindle": has_kindle,
            "kindle_price": kindle_price,
            "primary_book": current_book,
            "marketplaces": mkt_entries,
            "total_reviews": total_revs,
            "avg_rating": avg_rating,
            "reviews_7d": tot_7d,
            "reviews_30d": tot_30d,
            "last_review_date": last_date,
            "status_indicator": status_ind,
            "enabled": is_enabled,
            "created_at": primary.created_at
        })

    summaries.sort(key=lambda x: x["title"].lower())
    return summaries

def get_top_performers(books_summary: List[Dict[str, Any]], limit: int = 3) -> List[Dict[str, Any]]:
    return sorted(
        books_summary,
        key=lambda x: (x["stats"]["reviews_30d"], x["stats"]["avg_rating"], x["stats"]["total_reviews"]),
        reverse=True
    )[:limit]

def get_attention_books(books_summary: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    attention = []
    for item in books_summary:
        stats = item["stats"]
        latest_check = stats.get("latest_check")
        has_error = latest_check and (not latest_check.success or latest_check.status_code in ("PAGE_UNAVAILABLE", "PARSER_ERROR"))
        low_rating = stats["total_reviews"] > 0 and stats["avg_rating"] < 4.0
        
        recent_negative = False
        last_rev = stats.get("last_review")
        if last_rev and last_rev.rating <= 3.0:
            recent_negative = True
            
        if has_error or low_rating or recent_negative:
            reasons = []
            if has_error:
                reasons.append(f"Errore ultimo check: {latest_check.error_message or latest_check.status_code}")
            if low_rating:
                reasons.append(f"Rating sotto 4.0 ({stats['avg_rating']})")
            if recent_negative:
                reasons.append(f"Ultima recensione negativa ({last_rev.rating}★)")
                
            attention.append({
                "book": item["book"],
                "stats": stats,
                "reasons": reasons
            })
            
    return attention
