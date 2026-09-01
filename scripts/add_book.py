#!/usr/bin/env python3
"""
CLI script to add a new book to KDP Review Monitor using only its ASIN (or Amazon URL).
Automatically fetches metadata (title, cover, price, Kindle edition) and registers
the book across all 14 Amazon marketplaces.

Usage:
    python scripts/add_book.py B0XXXXXXXX
    python scripts/add_book.py "https://www.amazon.it/dp/B0XXXXXXXX"
    python scripts/add_book.py B0XXXXXXXX --no-check
"""

import sys
import os
import argparse
import logging

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.database import SessionLocal, engine, Base
from app.models import Book, AuditLog
from app.amazon.client import AmazonClient
from app.amazon.marketplace import MARKETPLACES, get_product_url
from app.routes.books import validate_asin
from app.reviews.monitor import run_book_check
from scripts.generate_static_dashboard import generate_static_html

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("add-book-cli")


def add_book_by_asin(raw_asin_or_url: str, check_immediately: bool = True) -> bool:
    """
    Adds a new book by ASIN across all Amazon marketplaces.
    """
    try:
        clean_asin = validate_asin(raw_asin_or_url)
    except ValueError as ve:
        logger.error(f"Errore ASIN non valido: {ve}")
        return False

    db = SessionLocal()
    try:
        # Check if ASIN already exists
        existing_count = db.query(Book).filter(Book.asin == clean_asin).count()
        if existing_count > 0:
            existing = db.query(Book).filter(Book.asin == clean_asin).first()
            logger.warning(
                f"Il libro con ASIN '{clean_asin}' ('{existing.title}') "
                f"è già presente nel catalogo ({existing_count} marketplace registrati)!"
            )
            return False

        logger.info(f"Ricerca metadati Amazon per ASIN: {clean_asin}...")
        client = AmazonClient()
        preview = client.check_asin_across_all_marketplaces(clean_asin)

        title = preview.get("title") or f"Libro Amazon KDP ({clean_asin})"
        cover_image = preview.get("cover_image_url")
        price = preview.get("price")
        has_kindle = preview.get("has_kindle", False)
        kindle_price = preview.get("kindle_price")

        logger.info(f"Titolo rilevato: '{title}'")
        if cover_image:
            logger.info(f"Copertina: {cover_image}")
        if price:
            logger.info(f"Prezzo cartaceo: {price}")
        if has_kindle:
            logger.info(f"Formato Kindle: Sì ({kindle_price or 'Prezzo n/d'})")

        target_marketplaces = list(MARKETPLACES.keys())
        added_books = []

        for mkt in target_marketplaces:
            prod_url = get_product_url(clean_asin, mkt)
            b = Book(
                asin=clean_asin,
                marketplace=mkt,
                title=title,
                product_url=prod_url,
                cover_image_url=cover_image,
                price=price,
                has_kindle=bool(has_kindle),
                kindle_price=kindle_price,
                enabled=True
            )
            db.add(b)
            added_books.append(b)

        audit = AuditLog(
            action="BOOK_ADDED_CLI",
            details=f"Aggiunto libro via CLI '{title}' (ASIN: {clean_asin}) su {len(added_books)} marketplace."
        )
        db.add(audit)
        db.commit()

        logger.info(f"✓ Registrato con successo '{title}' ({clean_asin}) su tutti i {len(added_books)} marketplace Amazon!")

        if check_immediately:
            logger.info("Esecuzione scansione iniziale recensioni...")
            for b in added_books:
                if b.marketplace == "amazon.it" or b.marketplace == "amazon.com":
                    try:
                        run_book_check(b, db, client=client)
                    except Exception as e:
                        logger.warning(f"Avviso scansione {b.marketplace}: {e}")

        # Update static GitHub Pages dashboard
        try:
            docs_dir = os.path.join(PROJECT_ROOT, "docs")
            os.makedirs(docs_dir, exist_ok=True)
            output_path = os.path.join(docs_dir, "index.html")
            generate_static_html(db, output_path=output_path)
            logger.info("Dashboard statica GitHub Pages aggiornata.")
        except Exception as e:
            logger.warning(f"Impossibile aggiornare dashboard statica: {e}")

        return True
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(
        description="Aggiunge un nuovo libro al monitor KDP inserendo semplicemente il suo codice ASIN."
    )
    parser.add_argument(
        "asin",
        help="Codice ASIN a 10 caratteri (es. B0H717X9ZL) oppure link completo Amazon."
    )
    parser.add_argument(
        "--no-check",
        action="store_true",
        help="Non eseguire la scansione immediata dopo l'aggiunta."
    )
    args = parser.parse_args()

    # Ensure DB tables exist
    Base.metadata.create_all(bind=engine)

    success = add_book_by_asin(args.asin, check_immediately=not args.no_check)
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
