#!/usr/bin/env python3
"""
CLI script to run KDP review monitoring check.
Can be run on schedule via GitHub Actions, Cron, or manual execution.
"""
import sys
import argparse
import logging
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.database import engine, Base, SessionLocal
from app.reviews.monitor import run_all_checks

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("kdp-monitor-cli")

def main():
    parser = argparse.ArgumentParser(description="Run KDP review monitor check.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force check execution regardless of the configured frequency schedule."
    )
    args = parser.parse_args()

    logger.info("Initializing database tables...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        logger.info(f"Starting review check (force={args.force})...")
        report = run_all_checks(db, force=args.force)
        
        if report.get("executed"):
            logger.info(f"Check finished: {report.get('books_checked')} books checked, {report.get('total_new_reviews')} new reviews found.")
        else:
            logger.info(f"Check skipped: {report.get('reason')}")
            
    except Exception as e:
        logger.error(f"Fatal error during monitor run: {e}", exc_info=True)
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    main()
